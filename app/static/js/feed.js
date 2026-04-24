// app/static/js/feed.js
console.log("Feed JS Module Loaded");

export async function likePost(id, btn) {
  try {
    const r = await fetch(`/posts/${id}/like`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      document.getElementById('score-' + id).textContent = d.upvotes - d.downvotes;
      btn.classList.toggle('active');
      const downBtn = btn.parentElement.querySelector('.downvote');
      if (downBtn) downBtn.classList.remove('active');
    }
  } catch(e) { console.error('Like failed:', e); }
}
window.likePost = likePost;

export async function dislikePost(id, btn) {
  try {
    const r = await fetch(`/posts/${id}/dislike`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      document.getElementById('score-' + id).textContent = d.upvotes - d.downvotes;
      btn.classList.toggle('active');
      const upBtn = btn.parentElement.querySelector('.upvote');
      if (upBtn) upBtn.classList.remove('active');
    }
  } catch(e) { console.error('Dislike failed:', e); }
}
window.dislikePost = dislikePost;

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

export async function likeComment(postId, commentId, btn) {
  try {
    const r = await fetch(`/posts/${postId}/comment/${commentId}/like`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      document.getElementById('c-score-' + commentId).textContent = d.upvotes - d.downvotes;
      btn.classList.toggle('active');
      const downBtn = btn.parentElement.querySelector('.downvote');
      if (downBtn) downBtn.classList.remove('active');
    }
  } catch(e) { console.error('Like failed:', e); }
}
window.likeComment = likeComment;

export async function dislikeComment(postId, commentId, btn) {
  try {
    const r = await fetch(`/posts/${postId}/comment/${commentId}/dislike`, { method: 'POST' });
    if(r.ok) {
      const d = await r.json();
      document.getElementById('c-score-' + commentId).textContent = d.upvotes - d.downvotes;
      btn.classList.toggle('active');
      const upBtn = btn.parentElement.querySelector('.upvote');
      if (upBtn) upBtn.classList.remove('active');
    }
  } catch(e) { console.error('Dislike failed:', e); }
}
window.dislikeComment = dislikeComment;

export async function reactComment(postId, commentId, type) {
  try {
    const r = await fetch(`/posts/${postId}/comment/${commentId}/react/${type}`, { method: 'POST' });
    if(r.ok) location.reload();
  } catch(e) { console.error('React failed:', e); }
}
window.reactComment = reactComment;

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

export async function deleteComment(commentId) {
  if (!confirm('Delete your comment? Replies will remain.')) return;
  try {
    const r = await fetch(`/posts/comment/${commentId}/delete`, { method: 'POST' });
    if (r.ok) {
      // Instantly replace the comment with the deleted placeholder (no full reload needed)
      const el = document.getElementById('comment-' + commentId);
      if (el) {
        // Keep only the first child (the comment div itself), remove action content
        const placeholder = document.createElement('div');
        placeholder.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:4px;opacity:0.45;';
        placeholder.innerHTML = '<div class="av" style="width:24px;height:24px;font-size:9px;">?</div><em style="font-size:13px;color:var(--text3);">[deleted by user]</em>';
        const removedMsg = document.createElement('div');
        removedMsg.style.cssText = 'font-size:13px;color:var(--text3);padding-left:30px;font-style:italic;';
        removedMsg.textContent = 'This comment has been removed.';
        // Clear inner html except for nested replies div
        const repliesDiv = el.querySelector(':scope > div[id^="comment-"]')?.parentElement;
        el.innerHTML = '';
        el.appendChild(placeholder);
        el.appendChild(removedMsg);
        if (repliesDiv) el.appendChild(repliesDiv);
      }
    } else {
      const d = await r.json();
      alert(d.detail || 'Failed to delete comment');
    }
  } catch(e) { console.error('Delete comment failed:', e); }
}
window.deleteComment = deleteComment;


// Utility layout operations hook
export function initFeed() {
  console.log("Strange Street Feed Engine Initialized");
}
