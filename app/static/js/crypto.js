// app/static/js/crypto.js

const DB_NAME = 'strange_crypto';
const STORE_NAME = 'keys';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function getPrivateKey(username) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const getReq = tx.objectStore(STORE_NAME).get(username + '_priv');
    getReq.onsuccess = () => resolve(getReq.result);
    getReq.onerror = () => reject(getReq.error);
  });
}

async function savePrivateKey(username, key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const req = tx.objectStore(STORE_NAME).put(key, username + '_priv');
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

// Convert ArrayBuffer to Base64 String
export function bufferToBase64(buf) {
  return btoa(String.fromCharCode.apply(null, new Uint8Array(buf)));
}
export function base64ToBuffer(b64) {
  const binary_string = atob(b64);
  const len = binary_string.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary_string.charCodeAt(i);
  }
  return bytes.buffer;
}

// Convert CryptoKey Public Key to PEM format to send to server
async function exportPublicKeyToPEM(publicKey) {
  const exported = await crypto.subtle.exportKey("spki", publicKey);
  const b64 = bufferToBase64(exported);
  return `-----BEGIN PUBLIC KEY-----\n${b64.match(/.{1,64}/g).join('\n')}\n-----END PUBLIC KEY-----`;
}

// Convert PEM to CryptoKey Object
export async function importPublicKeyFromPEM(pem) {
  const b64 = pem.replace(/-----[A-Z ]+-----/g, '').replace(/\n/g, '');
  const binaryDer = base64ToBuffer(b64);
  return await crypto.subtle.importKey(
    "spki",
    binaryDer,
    { name: "RSA-OAEP", hash: "SHA-256" },
    true,
    ["encrypt"]
  );
}

// Ensure user has a keypair. If not, generate and push public key to server
export async function initCrypto(username) {
  let privKey = await getPrivateKey(username);
  if (privKey) {
    console.log("[Crypto] Local private key found for", username);
    return;
  }
  
  console.log("[Crypto] Generating new RSA-OAEP Keypair for", username);
  const keyPair = await crypto.subtle.generateKey(
    {
      name: "RSA-OAEP",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256"
    },
    true,
    ["encrypt", "decrypt"]
  );

  // Save private key locally in IndexedDB (Never sent over network)
  await savePrivateKey(username, keyPair.privateKey);

  // Send public key to backend
  const pemKey = await exportPublicKeyToPEM(keyPair.publicKey);
  const r = await fetch('/users/me/public-key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ public_key: pemKey })
  });

  if (!r.ok) {
    console.error("[Crypto] Failed to sync public key to server", await r.text());
  } else {
    console.log("[Crypto] Synced public key to server successfully");
  }
}

// Encrypt a string message targeting a specific recipient's public key (PEM string)
export async function encryptMessage(recipientPem, plaintext) {
  if (!recipientPem) throw new Error("Recipient Public Key missing");
  
  const recipientKey = await importPublicKeyFromPEM(recipientPem);
  
  // Create an ephemeral AES-GCM symmetric key
  const aesKey = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    true,
    ["encrypt", "decrypt"]
  );

  // Encrypt the message with AES-GCM
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encodedMsg = new TextEncoder().encode(plaintext);
  const ciphertextBuf = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv },
    aesKey,
    encodedMsg
  );

  // Wrap (Encrypt) the AES key with the Recipient's RSA public key
  const rawAesKey = await crypto.subtle.exportKey("raw", aesKey);
  const encryptedAesKeyBuf = await crypto.subtle.encrypt(
    { name: "RSA-OAEP" },
    recipientKey,
    rawAesKey
  );

  // Pack everything into a JSON string and base64 encode it
  const payload = {
    iv: bufferToBase64(iv),
    encrypted_key: bufferToBase64(encryptedAesKeyBuf),
    ciphertext: bufferToBase64(ciphertextBuf)
  };
  return btoa(JSON.stringify(payload));
}

// Decrypt a base64 packed payload using my local private key
export async function decryptMessage(username, b64Payload) {
  try {
    const payload = JSON.parse(atob(b64Payload));
    const privKey = await getPrivateKey(username);
    if (!privKey) throw new Error("Private key not found in storage");

    const encryptedAesKeyBuf = base64ToBuffer(payload.encrypted_key);
    
    // Unwrap the AES key
    const rawAesKey = await crypto.subtle.decrypt(
      { name: "RSA-OAEP" },
      privKey,
      encryptedAesKeyBuf
    );
    
    const aesKey = await crypto.subtle.importKey(
      "raw",
      rawAesKey,
      { name: "AES-GCM" },
      false,
      ["decrypt"]
    );

    // Decrypt the ciphertext
    const iv = base64ToBuffer(payload.iv);
    const ciphertextBuf = base64ToBuffer(payload.ciphertext);
    
    const decryptedBuf = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: new Uint8Array(iv) },
      aesKey,
      ciphertextBuf
    );

    return new TextDecoder().decode(decryptedBuf);
  } catch (err) {
    console.error("[Crypto] Decryption failed:", err);
    return "🔒 [Encrypted Message]";
  }
}
