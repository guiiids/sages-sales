// JavaScript to call /api/query, get Markdown string, render with marked.js, and insert into chat-messages container

// First, ensure marked.js is loaded
function loadMarkedLibrary() {
  return new Promise((resolve, reject) => {
    if (typeof marked !== 'undefined') {
      console.log("marked-renderer.js: marked library already loaded");
      resolve();
      return;
    }
    
    console.log("marked-renderer.js: Loading marked library from CDN");
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/marked/marked.min.js';
    script.onload = () => {
      console.log("marked-renderer.js: marked library loaded successfully");
      // Configure marked.js
      marked.setOptions({
        gfm: true,          // GitHub Flavored Markdown
        breaks: true,       // Convert \n to <br>
        sanitize: false,    // Don't sanitize HTML (we handle this elsewhere)
        smartLists: true,   // Use smarter list behavior
        smartypants: true   // Use "smart" typographic punctuation
      });
      resolve();
    };
    script.onerror = () => {
      console.error("marked-renderer.js: Failed to load marked library");
      reject(new Error("Failed to load marked library"));
    };
    document.head.appendChild(script);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  console.log("marked-renderer.js: DOMContentLoaded");
  const chatMessagesContainer = document.getElementById('chat-messages');
  const queryInput = document.getElementById('query-input');
  const submitBtn = document.getElementById('submit-btn');

  // Load marked library immediately
  loadMarkedLibrary().catch(error => {
    console.error("marked-renderer.js: Error loading marked library:", error);
  });

  async function fetchAndRenderMarkdown(query) {
    try {
      // Ensure marked is loaded before proceeding
      await loadMarkedLibrary();
      
      console.log("marked-renderer.js: Fetching /api/query with query:", query);
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ query: query })
      });
      const data = await response.json();
      console.log("marked-renderer.js: Received response:", data);
      if (data.error) {
        chatMessagesContainer.innerHTML += `<div class="bot-message"><div class="bot-bubble">Error: ${data.error}</div></div>`;
        return;
      }
      const markdown = data.answer || '';
      const html = marked.parse(markdown);
      console.log("marked-renderer.js: Parsed markdown to HTML:", html);
      chatMessagesContainer.innerHTML += `<div class="bot-message"><div class="bot-bubble">${html}</div></div>`;
      chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
    } catch (error) {
      console.error("marked-renderer.js: Error fetching response", error);
      chatMessagesContainer.innerHTML += `<div class="bot-message"><div class="bot-bubble">Error fetching response</div></div>`;
    }
  }

  submitBtn.addEventListener('click', () => {
    console.log("marked-renderer.js: Submit button clicked");
    const query = queryInput.value.trim();
    if (!query) return;
    // Show user message
    chatMessagesContainer.innerHTML += `<div class="user-message"><div class="user-bubble">${query}</div></div>`;
    chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
    queryInput.value = '';
    fetchAndRenderMarkdown(query);
  });

  // Optional: submit on Enter key
  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitBtn.click();
    }
  });
});
