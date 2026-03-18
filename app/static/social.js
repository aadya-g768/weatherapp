const tabs = Array.from(document.querySelectorAll(".social-tab"));
const form = document.querySelector("#social-form");
const messageEl = document.querySelector("#social-message");
const statusEl = document.querySelector("#social-status");
const postsEl = document.querySelector("#social-posts");
const sortSelectEl = document.querySelector("#social-sort-select");
const SOCIAL_CLIENT_ID_KEY = "social_client_id";

let activeTab = "Help";
let isPublishing = false;
const sortModeByTab = {
  Help: "replies",
  Experiences: "replies",
  Feedback: "replies",
  Questions: "replies",
};

const setStatus = (message) => {
  statusEl.textContent = message;
};

const getSocialClientId = () => {
  try {
    const existing = (localStorage.getItem(SOCIAL_CLIENT_ID_KEY) || "").trim();
    if (existing) {
      return existing;
    }

    const generated = (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function")
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(SOCIAL_CLIENT_ID_KEY, generated);
    return generated;
  } catch {
    return "fallback-client";
  }
};

const formatPostedDate = (value) => {
  if (!value) {
    return "Unknown date";
  }
  return String(value).split("T")[0];
};

const getReplyCount = (post) => (Array.isArray(post?.replies) ? post.replies.length : 0);

const getSortModeForTab = (tab) => sortModeByTab[tab] || "replies";

const compareByNewest = (left, right) => {
  const leftTime = new Date(left.created_at || 0).getTime();
  const rightTime = new Date(right.created_at || 0).getTime();
  return rightTime - leftTime;
};

const sortRepliesForMode = (replies, sortMode) => {
  const safeReplies = Array.isArray(replies) ? [...replies] : [];
  if (sortMode !== "likes") {
    return safeReplies;
  }

  return safeReplies.sort((left, right) => {
    const likesDiff = (Number(right.likes) || 0) - (Number(left.likes) || 0);
    if (likesDiff !== 0) {
      return likesDiff;
    }
    return compareByNewest(left, right);
  });
};

const renderPosts = (tab, posts) => {
  if (!Array.isArray(posts) || posts.length === 0) {
    postsEl.innerHTML = `<div class="result-item">No posts yet in ${tab}. Be the first to publish.</div>`;
    return;
  }

  const sortMode = getSortModeForTab(tab);
  const orderedPosts = [...posts].sort((left, right) => {
    if (sortMode === "likes") {
      const likesDiff = (Number(right.likes) || 0) - (Number(left.likes) || 0);
      if (likesDiff !== 0) {
        return likesDiff;
      }
      return compareByNewest(left, right);
    }

    const repliesDiff = getReplyCount(right) - getReplyCount(left);
    if (repliesDiff !== 0) {
      return repliesDiff;
    }

    const likesDiff = (Number(right.likes) || 0) - (Number(left.likes) || 0);
    if (likesDiff !== 0) {
      return likesDiff;
    }

    return compareByNewest(left, right);
  });

  const cards = orderedPosts
    .map(
      (post) => `
      <article class="result-card social-post">
        <div class="social-main-row">
          <div class="social-main-content">
            <div class="result-title">${tab}</div>
            <div class="social-meta">Posted ${formatPostedDate(post.created_at)}</div>
            <div>${post.message}</div>
          </div>
          <div class="social-like-stack">
            <div class="social-like-count">${Number(post.likes) || 0}</div>
            <button type="button" class="social-like-button" data-like-target="post" data-post-id="${post.id}" title="Likes: ${Number(post.likes) || 0}" aria-label="Like post. Current likes ${Number(post.likes) || 0}">
              👍
            </button>
          </div>
        </div>
        <div class="social-replies">
          ${(Array.isArray(post.replies) && post.replies.length > 0)
            ? sortRepliesForMode(post.replies, sortMode)
                .map(
                  (reply) => `
                <div class="social-reply-item">
                  <div class="social-reply-content">
                    <div>↪ ${reply.message}</div>
                    <div class="social-meta">Replied ${formatPostedDate(reply.created_at)}</div>
                  </div>
                </div>
              `
                )
                .join("")
            : '<div class="social-meta">No replies yet.</div>'}
        </div>
        ${
          tab === "Feedback"
            ? ""
            : `<form class="social-reply-form" data-post-id="${post.id}">
          <input type="text" name="reply" placeholder="Write a reply..." required />
          <button type="submit">Reply</button>
        </form>`
        }
      </article>
    `
    )
    .join("");

  postsEl.innerHTML = cards;
};

const fetchPosts = async (tab) => {
  setStatus(`Loading ${tab}...`);
  try {
    const response = await fetch(`/api/social/posts?tab=${encodeURIComponent(tab)}`);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to load posts.");
      return;
    }

    renderPosts(tab, data.posts || []);
    setStatus(`Showing ${tab}.`);
  } catch {
    setStatus("Network error while loading posts.");
  }
};

const setActiveTab = async (tab) => {
  activeTab = tab;
  tabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  if (sortSelectEl) {
    sortSelectEl.value = getSortModeForTab(tab);
  }
  await fetchPosts(tab);
};

tabs.forEach((button) => {
  button.addEventListener("click", async () => {
    await setActiveTab(button.dataset.tab);
  });
});

if (sortSelectEl) {
  sortSelectEl.addEventListener("change", async () => {
    const nextSortMode = sortSelectEl.value === "likes" ? "likes" : "replies";
    sortModeByTab[activeTab] = nextSortMode;
    await fetchPosts(activeTab);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isPublishing) {
    return;
  }

  const message = messageEl.value.trim();
  if (!message) {
    setStatus("Message cannot be empty.");
    return;
  }

  isPublishing = true;
  setStatus("Publishing...");

  try {
    const response = await fetch("/api/social/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab: activeTab, message }),
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to publish post.");
      return;
    }

    messageEl.value = "";
    renderPosts(activeTab, data.posts || []);
    setStatus("Published successfully.");
  } catch {
    setStatus("Network error while publishing.");
  } finally {
    isPublishing = false;
  }
});

postsEl.addEventListener("submit", async (event) => {
  const replyForm = event.target.closest(".social-reply-form");
  if (!replyForm) {
    return;
  }

  event.preventDefault();
  const replyInput = replyForm.querySelector("input[name='reply']");
  const message = (replyInput?.value || "").trim();
  const postId = Number(replyForm.dataset.postId);

  if (!message) {
    setStatus("Reply cannot be empty.");
    return;
  }

  try {
    const response = await fetch("/api/social/replies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab: activeTab, post_id: postId, message }),
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to publish reply.");
      return;
    }

    replyInput.value = "";
    await fetchPosts(activeTab);
    setStatus("Reply published.");
  } catch {
    setStatus("Network error while publishing reply.");
  }
});

postsEl.addEventListener("click", async (event) => {
  const likeButton = event.target.closest(".social-like-button");
  if (!likeButton) {
    return;
  }

  const postId = Number(likeButton.dataset.postId);

  if (!Number.isInteger(postId) || postId <= 0) {
    setStatus("Invalid post id.");
    return;
  }

  const endpoint = "/api/social/posts/like";
  const payload = { tab: activeTab, post_id: postId, client_id: getSocialClientId() };

  setStatus("Saving like...");

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to save like.");
      return;
    }

    await fetchPosts(activeTab);
    setStatus("Like saved.");
  } catch {
    setStatus("Network error while saving like.");
  }
});

setActiveTab(activeTab);
