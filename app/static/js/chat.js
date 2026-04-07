// app/static/js/chat.js

// Auto-scroll to bottom
export function initChatScroll() {
  const body = document.getElementById('msg-body');
  if(body) body.scrollTop = body.scrollHeight;
}

// Delete Message
export async function deleteMessage(id) {
  console.log(`[Chat] Deleting message ${id}...`);
  if (!confirm('Delete this message for everyone?')) return;
  try {
    const res = await fetch(`/messages/${id}/delete`, {method: 'POST'});
    if(res.ok) {
      const el = document.getElementById(`msg-${id}`);
      if(el) {
        el.style.opacity = '0.5';
        el.style.pointerEvents = 'none';
        setTimeout(() => el.remove(), 300);
      }
      console.log(`[Chat] Message ${id} deleted.`);
    } else {
      const data = await res.json();
      console.error(`[Chat] Delete failed:`, data);
      alert('Failed to delete: ' + (data.detail || res.statusText));
    }
  } catch(e) {
    console.error(`[Chat] Error deleting message:`, e);
    alert('Error: ' + e);
  }
}
// Attach to window immediately
if (typeof window !== 'undefined') {
  window.deleteMessage = deleteMessage;
}

// File Preview
export function updateFileName(input) {
  const preview = document.getElementById('file-preview');
  if (input.files && input.files[0]) {
    preview.style.display = 'block';
    preview.textContent = "📎 " + input.files[0].name;
    document.getElementById('msg-input').removeAttribute('required');
  } else {
    preview.style.display = 'none';
  }
}
window.updateFileName = updateFileName;

export function initChatForm(recipientPubKey) {
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', async function(e) {
      if (form.dataset.submitting) return;
      e.preventDefault();
      
      const inp = document.getElementById('msg-input');
      const file = document.getElementById('media-input');
      if(!inp.value.trim() && !file.files.length) return;
      
      form.dataset.submitting = "true";
      const btn = form.querySelector('button[type="submit"]');
      const originalText = btn.textContent;
      
      try {
        if (recipientPubKey && inp.value.trim() && !inp.value.startsWith("E2E::")) {
          btn.textContent = "Encrypting...";
          btn.disabled = true;
          const { encryptMessage } = await import('/static/js/crypto.js');
          const encryptedBlob = await encryptMessage(recipientPubKey, inp.value);
          inp.value = "E2E::" + encryptedBlob;
        }
      } catch(err) {
        console.error("[Chat] Encryption failed, sending as plaintext.", err);
      } finally {
        form.submit();
      }
    });
  }
}


// Decrypt all messages in the feed upon load
export async function decryptChatFeed(myUsername) {
  const bubbles = document.querySelectorAll('.msg-text');
  const { decryptMessage } = await import('/static/js/crypto.js');
  
  for (const el of bubbles) {
    const raw = el.dataset.content;
    if (raw && raw.startsWith("E2E::")) {
      const b64Payload = raw.substring(5);
      const plaintext = await decryptMessage(myUsername, b64Payload);
      el.textContent = plaintext;
    } else {
      // Legacy plaintext message fallback
      el.textContent = raw;
    }
  }
}

export async function revealNext(connectionId) {
  console.log(`[Reveal] Initiating reveal for connection ${connectionId}...`);
  try {
    const r = await fetch(`/connections/${connectionId}/reveal`, {method:'POST'});
    const d = await r.json();
    console.log(`[Reveal] Server response:`, d);
    if (r.ok) {
      location.reload();
    } else {
      alert(d.error || d.message || 'Reveal failed');
    }
  } catch (e) {
    console.error(`[Reveal] Fetch error:`, e);
    alert('Network error: ' + e);
  }
}


window.revealNext = revealNext;

// Emoji Picker Initialization
export async function initEmojiPicker() {
  await import('https://cdn.jsdelivr.net/npm/emoji-picker-element@^1/index.js');
  const trigger = document.getElementById('emoji-trigger');
  const container = document.getElementById('emoji-picker-container');
  const input = document.getElementById('msg-input');
  
  if (!trigger || !container || !input) return;

  const picker = document.createElement('emoji-picker');
  picker.classList.add('dark');
  picker.style.cssText = '--background:var(--bg2);--border-color:var(--border);--button-hover-background:var(--bg3);--indicator-color:var(--red);--input-border-color:var(--border2);';
  container.appendChild(picker);

  trigger.addEventListener('click', () => {
    container.style.display = container.style.display === 'none' ? 'block' : 'none';
  });

  picker.addEventListener('emoji-click', event => {
    input.value += event.detail.unicode;
    container.style.display = 'none';
    input.focus();
  });
  
  document.addEventListener('click', (e) => {
    if (!trigger.contains(e.target) && !container.contains(e.target)) {
      container.style.display = 'none';
    }
  });
}
