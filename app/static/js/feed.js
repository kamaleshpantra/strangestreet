// app/static/js/feed.js

export async function likePost(id, btn) {
  try {
    const r = await fetch(`/posts/${id}/like`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      document.getElementById('lc-' + id).textContent = d.count;
      btn.classList.toggle('up', d.liked);
    }
  } catch(e) { console.error('Like failed:', e); }
}
window.likePost = likePost;

export async function followUser(u, btn) {
  try {
    const r = await fetch(`/users/${u}/follow`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      btn.textContent = d.following ? 'Following' : 'Follow';
      btn.classList.toggle('on', d.following);
      const folCountEl = document.getElementById('fol-count');
      if (folCountEl) folCountEl.textContent = d.follower_count;
    }
  } catch(e) { console.error('Follow failed:', e); }
}
window.followUser = followUser;

export function filterCat(btn, cat) {
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.post').forEach(p => {
    p.style.display = (cat === 'all' || p.dataset.cat === cat) ? 'flex' : 'none';
  });
}
window.filterCat = filterCat;

export async function reactPost(id, type) {
  try {
    const r = await fetch(`/posts/${id}/react/${type}`, { method: 'POST' });
    if(r.ok) location.reload();
  } catch(e) { console.error('React failed:', e); }
}
window.reactPost = reactPost;

export async function bookmarkPost(id, btn) {
  try {
    const r = await fetch(`/posts/${id}/bookmark`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      btn.style.opacity = d.bookmarked ? '1' : '0.4';
    }
  } catch(e) { console.error('Bookmark failed:', e); }
}
window.bookmarkPost = bookmarkPost;

export async function votePoll(postId, optId) {
  try {
    const r = await fetch(`/posts/${postId}/poll/${optId}/vote`, { method: 'POST' });
    if(r.ok) location.reload();
  } catch(e) { console.error('Vote failed:', e); }
}
window.votePoll = votePoll;

export async function deletePost(id) {
  if (!confirm('Are you sure you want to delete this post?')) return;
  try {
    const r = await fetch(`/posts/${id}/delete`, { method: 'POST' });
    if(r.ok) {
      location.reload(); 
    } else {
      const d = await r.json();
      alert(d.error || 'Failed to delete post');
    }
  } catch(e) { console.error('Delete failed:', e); }
}
window.deletePost = deletePost;


// Utility layout operations hook
export function initFeed() {
  console.log("Strange Street Feed Engine Initialized");
}
