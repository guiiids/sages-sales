// Developer Evaluation Chat Interface
// This script handles the step-by-step parameter collection for developer evaluation mode

// Helper functions that might be missing from the global scope
// These will be used if the global versions don't exist
const ChatHelpers = {
  // Add a user message to the chat
  addUserMessage: function (message) {
    if (typeof window.addUserMessage === 'function') {
      window.addUserMessage(message);
    } else {
      console.log('User message:', message);
      // Create a fallback implementation
      const messagesContainer = document.querySelector('.messages-container');
      if (messagesContainer) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user-message';
        messageDiv.innerHTML = `<div class="message-content">${message}</div>`;
        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }
    }
  },

  // Add a bot message to the chat
  addBotMessage: function (message) {
    if (typeof window.addBotMessage === 'function') {
      window.addBotMessage(message);
    } else {
      console.log('Bot message:', message);
      // Create a fallback implementation
      const messagesContainer = document.querySelector('.messages-container');
      if (messagesContainer) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message bot-message';
        messageDiv.innerHTML = `<div class="message-content">${message}</div>`;

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        // Inject mt-4 class to list items after message is added
        messageDiv.querySelectorAll('ol, ul').forEach(list => {
          list.querySelectorAll('li + li').forEach(li => {
            li.classList.add('mt-4');
          });
        });
      }
    }
  },

  // Escape HTML to prevent XSS
  escapeHtml: function (text) {
    if (typeof window.escapeHtml === 'function') {
      return window.escapeHtml(text);
    } else {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
  },

  // Format message with markdown rendering
  formatMessage: function (text) {
    if (typeof window.formatMessage === 'function') {
      return window.formatMessage(text);
    } else {
      try {
        // Try to use marked.js if available
        if (typeof marked !== 'undefined') {
          // Pre-process special cases before passing to marked.js
          let processedText = text.replace(
            /\[(\d+)\]/g,
            '<a href="#source-$1" class="citation-link text-xs text-blue-600 hover:underline" data-source-id="$1">[$1]</a>'
          );

          return marked.parse(processedText, {
            gfm: true,
            breaks: true,
            sanitize: false,
            smartLists: true,
            smartypants: true
          });
        } else {
          // Fallback to basic formatting
          return text.replace(/\n/g, '<br>');
        }
      } catch (error) {
        console.error('Error rendering markdown:', error);
        // Fallback to basic formatting
        return text.replace(/\n/g, '<br>');
      }
    }
  },

  // Add typing indicator
  addTypingIndicator: function () {
    if (typeof window.addTypingIndicator === 'function') {
      return window.addTypingIndicator();
    } else {
      console.log('Adding typing indicator');
      // Create a fallback implementation
      const messagesContainer = document.querySelector('.messages-container');
      if (messagesContainer) {
        const indicatorDiv = document.createElement('div');
        indicatorDiv.className = 'typing-indicator';
        indicatorDiv.innerHTML = '<span></span><span></span><span></span>';
        messagesContainer.appendChild(indicatorDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return indicatorDiv;
      }
      return null;
    }
  },

  // Open console drawer
  openDrawer: function () {
    if (typeof window.openDrawer === 'function') {
      window.openDrawer();
    } else {
      console.log('Opening console drawer');
      // Try to find and show the console drawer
      const drawer = document.querySelector('.console-drawer');
      if (drawer) {
        drawer.classList.add('open');
      }
    }
  },

  // Get logs container
  getLogsContainer: function () {
    if (typeof window.logsContainer !== 'undefined') {
      return window.logsContainer;
    } else {
      return document.querySelector('.logs-container') || document.createElement('div');
    }
  }
};

// Create a self-contained module to avoid polluting the global namespace
const DevEvalChat = {
  // Constants
  STATE: {
    IDLE: 'idle',
    QUERY: 'query',
    PROMPT: 'prompt',
    TEMPERATURE: 'temperature',
    TOP_P: 'top_p',
    MAX_TOKENS: 'max_tokens',
    PROCESSING: 'processing'
  },

  // State variables
  currentState: 'idle',
  initialized: false,
  params: {
    query: '',
    prompt: '',
    temperature: 0.3,
    top_p: 1.0,
    max_tokens: 1000
  },

  // Initialize the module
  init: function () {
    if (this.initialized) {
      console.log('DevEvalChat already initialized, skipping');
      return;
    }

    console.log('Developer Evaluation Chat Interface loaded');

    // Store references to DOM elements
    // Prioritize new input if available
    this.queryInput = document.getElementById('new-query-input') || document.getElementById('query-input');
    this.submitBtn = document.getElementById('submit-btn');
    this.devModeBtn = document.getElementById('toggle-developer-mode-btn');

    console.log('DOM Elements:', {
      queryInput: this.queryInput ? 'found' : 'not found',
      submitBtn: this.submitBtn ? 'found' : 'not found',
      devModeBtn: this.devModeBtn ? 'found' : 'not found'
    });

    // Only proceed if we found all required elements
    if (!this.queryInput || !this.submitBtn) {
      console.error('Required DOM elements not found');
      return;
    }

    // Save original submitQuery function
    if (typeof window.submitQuery === 'function') {
      this.originalSubmitQuery = window.submitQuery;

      // Replace submitQuery with our version
      window.submitQuery = function () {
        // If eVal mode is active, use our handler
        if (window.isDeveloperMode) {
          DevEvalChat.handleSubmit();
        } else {
          // Otherwise use the original
          DevEvalChat.originalSubmitQuery();
        }
      };
      console.log('Overrode submitQuery function');
    } else {
      console.error('window.submitQuery is not a function');
    }

    // Add event listener for eVal mode button
    if (this.devModeBtn) {
      // Remove any existing click listeners to avoid duplicates
      const newBtn = this.devModeBtn.cloneNode(true);
      this.devModeBtn.parentNode.replaceChild(newBtn, this.devModeBtn);
      this.devModeBtn = newBtn;

      this.devModeBtn.addEventListener('click', function () {
        // Toggle eVal mode
        window.isDeveloperMode = !window.isDeveloperMode;
        console.log('eVal mode toggled to:', window.isDeveloperMode);

        // Update UI based on the new mode
        if (window.isDeveloperMode) {
          DevEvalChat.currentState = DevEvalChat.STATE.QUERY;
          DevEvalChat.queryInput.placeholder = "Enter your query...";
          DevEvalChat.devModeBtn.classList.add('bg-green-600', 'hover:bg-green-700');
          DevEvalChat.devModeBtn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
          DevEvalChat.devModeBtn.textContent = 'eVal mode: ON';
          ChatHelpers.addBotMessage("Developer Evaluation mode enabled. Please enter your query for developer analysis.");
        } else {
          DevEvalChat.currentState = DevEvalChat.STATE.IDLE;
          DevEvalChat.queryInput.placeholder = "Ask me anything about our knowledge base...";
          DevEvalChat.devModeBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
          DevEvalChat.devModeBtn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
          DevEvalChat.devModeBtn.textContent = 'eVal';
          ChatHelpers.addBotMessage("Standard chat mode enabled.");
        }

        console.log('Current state:', DevEvalChat.currentState);
      });
      console.log('Added event listener to eVal mode button');
      // Magic wand click handler inside DevEvalChat.init
      this.magicBtn = document.getElementById('magic-btn');
      if (this.magicBtn) {
        this.magicBtn.addEventListener('click', () => {
          const grabbedInputTxt = this.queryInput.value;
          console.log('Magic button clicked, grabbedInputTxt:', grabbedInputTxt);
        });
      }
    }

    // Check if we're already in eVal mode
    if (window.isDeveloperMode) {
      this.currentState = this.STATE.QUERY;
      if (this.queryInput) {
        this.queryInput.placeholder = "Enter your query...";
      }
      console.log('Initialized in eVal mode');
    }

    this.initialized = true;

    // Attach magic-wand click handler once initialized
    const magicBtn = document.getElementById('magic-btn');
    if (magicBtn && this.queryInput) {
      magicBtn.addEventListener('click', () => {
        const grabbedInputTxt = this.queryInput.value;
        console.log('Magic button clicked, grabbedInputTxt:', grabbedInputTxt);
      });
    }
  },

  // Handle form submission
  handleSubmit: function () {
    const userInput = this.queryInput.value.trim();
    if (!userInput) return;

    // Add user message to chat
    ChatHelpers.addUserMessage(userInput);
    this.queryInput.value = '';
    if (this.submitBtn) {
      this.submitBtn.disabled = false;
    }

    // Handle the current state
    this.handleUserInput(userInput);
  },

  // Handle user input based on current state
  handleUserInput: function (userInput) {
    switch (this.currentState) {
      case this.STATE.IDLE:
      case this.STATE.QUERY:
        this.params.query = userInput;
        ChatHelpers.addBotMessage("Enter prompt/instructions (or leave blank for default):");
        if (this.queryInput) {
          this.queryInput.placeholder = "Enter prompt/instructions...";
        }
        this.currentState = this.STATE.PROMPT;
        break;

      case this.STATE.PROMPT:
        this.params.prompt = userInput;
        ChatHelpers.addBotMessage(`Set temperature (0.0-2.0) (default 0.3):`);
        if (this.queryInput) {
          this.queryInput.placeholder = "Enter temperature (0.0-2.0)...";
        }
        this.currentState = this.STATE.TEMPERATURE;
        break;

      case this.STATE.TEMPERATURE:
        // Validate temperature input
        let temp = parseFloat(userInput);
        if (userInput === '') {
          // Use default
          temp = 0.3;
        } else if (isNaN(temp) || temp < 0 || temp > 2) {
          ChatHelpers.addBotMessage("Invalid temperature value. Please enter a number between 0.0 and 2.0:");
          return; // Stay on this step
        }
        this.params.temperature = temp;
        ChatHelpers.addBotMessage(`Set top_p (0.0-1.0) (default 1.0):`);
        if (this.queryInput) {
          this.queryInput.placeholder = "Enter top_p (0.0-1.0)...";
        }
        this.currentState = this.STATE.TOP_P;
        break;

      case this.STATE.TOP_P:
        // Validate top_p input
        let topP = parseFloat(userInput);
        if (userInput === '') {
          // Use default
          topP = 1.0;
        } else if (isNaN(topP) || topP < 0 || topP > 1) {
          ChatHelpers.addBotMessage("Invalid top_p value. Please enter a number between 0.0 and 1.0:");
          return; // Stay on this step
        }
        this.params.top_p = topP;
        ChatHelpers.addBotMessage(`Set max_tokens (1-4000) (default 1000):`);
        if (this.queryInput) {
          this.queryInput.placeholder = "Enter max_tokens (1-4000)...";
        }
        this.currentState = this.STATE.MAX_TOKENS;
        break;

      case this.STATE.MAX_TOKENS:
        // Validate max_tokens input
        let maxTokens = parseInt(userInput);
        if (userInput === '') {
          // Use default
          maxTokens = 1000;
        } else if (isNaN(maxTokens) || maxTokens < 1 || maxTokens > 4000) {
          ChatHelpers.addBotMessage("Invalid max_tokens value. Please enter a number between 1 and 4000:");
          return; // Stay on this step
        }
        this.params.max_tokens = maxTokens;

        // All parameters collected, run the evaluation
        this.processEvaluation();
        break;

      case this.STATE.PROCESSING:
        // Ignore input while processing
        break;
    }
  },

  // Process the evaluation with collected parameters
  processEvaluation: function () {
    this.currentState = this.STATE.PROCESSING;

    // Show parameters being used
    let paramsDisplay = `
      <strong>Query:</strong> ${ChatHelpers.escapeHtml(this.params.query)}<br>
      <strong>Parameters:</strong><br>
      - Temperature: ${this.params.temperature}<br>
      - Top P: ${this.params.top_p}<br>
      - Max Tokens: ${this.params.max_tokens}<br>
    `;

    if (this.params.prompt) {
      paramsDisplay += `<strong>Custom Prompt:</strong> ${ChatHelpers.escapeHtml(this.params.prompt)}<br>`;
    }

    ChatHelpers.addBotMessage(paramsDisplay);
    ChatHelpers.addBotMessage("Running developer evaluation...");

    const typingIndicator = ChatHelpers.addTypingIndicator();

    // Reset for next evaluation
    this.currentState = this.STATE.QUERY;
    if (this.queryInput) {
      this.queryInput.placeholder = "Enter your query...";
    }

    // Call the API
    fetch('/api/dev_eval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: this.params.query,
        prompt: this.params.prompt,
        parameters: {
          temperature: this.params.temperature,
          top_p: this.params.top_p,
          max_tokens: this.params.max_tokens
        }
      })
    })
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error! Status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        if (typingIndicator) typingIndicator.remove();

        if (data.error) {
          ChatHelpers.addBotMessage('Error: ' + data.error);
          this.currentState = this.STATE.QUERY;
          return;
        }

        // Show LLM result (the actual answer to the query)
        ChatHelpers.addBotMessage('<strong>LLM Output:</strong><br>' + ChatHelpers.formatMessage(data.result));

        // Show sources if available
        if (data.sources && data.sources.length > 0) {
          let sourcesText = '<strong>Sources:</strong><br><div class="sources-container">';
          data.sources.forEach((source, index) => {
            // Create a unique ID for each source for citation linking
            const sourceId = `source-${index + 1}`;

            // Start source item with ID for citation links
            sourcesText += `<div id="${sourceId}" class="source-item mb-2 p-2 bg-gray-50 rounded">`;

            // Handle different source formats
            let sourceTitle = '';
            let sourceContent = '';

            if (typeof source === 'string') {
              // For string sources, use the first 100 chars as title and the rest as content
              if (source.length > 100) {
                sourceTitle = source.substring(0, 100) + '...';
                sourceContent = source;
              } else {
                sourceTitle = source;
                sourceContent = '';
              }
            } else if (typeof source === 'object') {
              // Extract title and content from source object
              sourceTitle = source.title || source.id || `Source ${index + 1}`;
              sourceContent = source.content || '';
            }

            // Truncate content if it's too long (more than 150 chars)
            const isLongContent = sourceContent.length > 150;
            const truncatedContent = isLongContent ?
              sourceContent.substring(0, 150) + '...' :
              sourceContent;

            // Create HTML with collapsible content
            sourcesText += `
              <div>
                <strong>[${index + 1}]</strong> <strong>${sourceTitle}</strong>
                <div class="source-content">${truncatedContent}</div>
                ${isLongContent ?
                `<div class="source-full-content hidden">${sourceContent}</div>
                   <button class="toggle-source-btn text-blue-600 text-xs mt-1 hover:underline">Show more</button>`
                : ''}
              </div>
            `;

            sourcesText += '</div>';
          });
          sourcesText += '</div>';

          ChatHelpers.addBotMessage(sourcesText);

          // Add click event for citation links and toggle buttons
          setTimeout(() => {
            // Handle citation links
            document.querySelectorAll('.citation-link').forEach(link => {
              link.addEventListener('click', function (e) {
                e.preventDefault();
                const sourceId = this.getAttribute('data-source-id');
                const sourceElement = document.getElementById(`source-${sourceId}`);
                if (sourceElement) {
                  sourceElement.scrollIntoView({ behavior: 'smooth' });
                  sourceElement.classList.add('bg-yellow-100');
                  setTimeout(() => {
                    sourceElement.classList.remove('bg-yellow-100');
                  }, 2000);
                }
              });
            });

            // Handle toggle source buttons
            document.querySelectorAll('.toggle-source-btn').forEach(btn => {
              btn.addEventListener('click', function () {
                const parentDiv = this.closest('.source-item');
                if (!parentDiv) return;

                const truncatedEl = parentDiv.querySelector('.source-content');
                const fullEl = parentDiv.querySelector('.source-full-content');

                if (!truncatedEl || !fullEl) return;

                if (truncatedEl.classList.contains('hidden')) {
                  // Show truncated, hide full
                  truncatedEl.classList.remove('hidden');
                  fullEl.classList.add('hidden');
                  this.textContent = 'Show more';
                } else {
                  // Show full, hide truncated
                  truncatedEl.classList.add('hidden');
                  fullEl.classList.remove('hidden');
                  this.textContent = 'Show less';
                }
              });
            });
          }, 100);
        }

        // Show developer evaluation
        if (data.developer_evaluation) {
          ChatHelpers.addBotMessage('<strong>Developer Evaluation:</strong><br>' + ChatHelpers.formatMessage(data.developer_evaluation));
        } else {
          ChatHelpers.addBotMessage('<strong>Developer Evaluation:</strong><br>No evaluation available. The llm_summary module might be missing.');
        }

        // Show download links and view in console button
        if (data.download_url_json || data.download_url_md) {
          let downloadLinks = '<strong>Report:</strong><br><div class="flex flex-wrap gap-2 mt-2">';

          if (data.download_url_json) {
            downloadLinks += `<a href="${data.download_url_json}" download class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 inline-block">Download JSON</a>`;
          }

          if (data.download_url_md) {
            downloadLinks += `<a href="${data.download_url_md}" download class="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 inline-block">Download Markdown</a>`;
          }

          if (data.markdown_report) {
            downloadLinks += `<button id="view-in-console-btn" class="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 inline-block">View in Console</button>`;
          }

          downloadLinks += '</div>';
          ChatHelpers.addBotMessage(downloadLinks);

          // Add event listener for "View in Console" button
          setTimeout(() => {
            const viewInConsoleBtn = document.getElementById('view-in-console-btn');
            if (viewInConsoleBtn) {
              viewInConsoleBtn.addEventListener('click', function () {
                // Open console drawer
                ChatHelpers.openDrawer();

                // Clear console
                const logsContainer = ChatHelpers.getLogsContainer();
                if (logsContainer) {
                  logsContainer.innerHTML = '';
                }

                // Add styled markdown to console
                const mdContainer = document.createElement('div');
                mdContainer.className = 'p-4 bg-white dark:bg-black text-white rounded shadow';
                mdContainer.style.fontFamily = 'monospace';
                mdContainer.style.whiteSpace = 'pre-wrap';
                mdContainer.style.fontSize = '14px';
                mdContainer.style.lineHeight = '1.5';

                // Format markdown with syntax highlighting
                let formattedMd = data.markdown_report
                  .replace(/^# (.*$)/gm, '<h1 class="text-xl font-bold text-blue-800 mt-4 mb-2">$1</h1>')
                  .replace(/^## (.*$)/gm, '<h2 class="text-lg font-bold text-blue-600 mt-3 mb-2">$1</h2>')
                  .replace(/^### (.*$)/gm, '<h3 class="text-md font-bold text-blue-500 mt-2 mb-1">$1</h3>')
                  .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                  .replace(/\*(.*?)\*/g, '<em>$1</em>')
                  .replace(/```([\s\S]*?)```/g, '<pre class="bg-gray-100 p-2 rounded my-2 overflow-x-auto">$1</pre>')
                  .replace(/^- (.*$)/gm, '• $1');

                mdContainer.innerHTML = formattedMd;
                if (logsContainer) {
                  logsContainer.appendChild(mdContainer);
                  logsContainer.scrollTop = 0;
                }
              });
            }
          }, 100);
        }
      })
      .catch(error => {
        if (typingIndicator) typingIndicator.remove();
        console.error('API error:', error);
        ChatHelpers.addBotMessage('Sorry, an error occurred: ' + error.message);
        this.currentState = this.STATE.QUERY;
      });
  }
};

// Initialize the module when the DOM is ready
document.addEventListener('DOMContentLoaded', function () {
  console.log('DOM content loaded, initializing DevEvalChat');
  DevEvalChat.init();
  // Duplicate listeners removed to prevent conflict with index.html logic
  // The magic button logic is now robustly handled in index.html with visual feedback and proper error handling.
  /*
  // Magic button click handler after init
  document.getElementById('magic-btn')?.addEventListener('click', function () {
    const btn = this;
    btn.disabled = true;
    const origIcon = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    const input = document.getElementById('query-input');
    const inputText = input.value;
    fetch('/api/magic_query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_text: inputText })
    })
      .then(response => response.json())
      .then(data => {
        if (data.error) {
          console.error('Magic query error:', data.error);
          ChatHelpers.addBotMessage('Error: ' + data.error);
        } else {
          input.value = data.output;
          // Store the enhanced flag as a data attribute on the input element
          if (data.is_enhanced) {
            input.dataset.enhanced = 'true';
            console.log('Query enhanced with magic wand');
          }
        }
      })
      .catch(error => {
        console.error('Network error during magic query:', error);
        ChatHelpers.addBotMessage('Network error: ' + error.message);
      })
      .finally(() => {
        btn.disabled = false;
        btn.innerHTML = origIcon;
        // Hide mobile status indicator when enhancement completes
        if (window.mobileStatusHelpers) {
          window.mobileStatusHelpers.success('Query enhanced!');
        }
      });
  });

  // Magic button 2XL click handler
  const magicBtn2xl = document.getElementById('magic-btn-2xl');
  if (magicBtn2xl) {
    magicBtn2xl.addEventListener('click', function () {
      const text = document.getElementById('query-input').value.trim();
      if (!text) return;

      // Store references to button and original icon to ensure they're accessible in all callbacks
      const btn = this;
      const origIcon = btn.innerHTML;

      // Log the start of the process
      console.log('Magic 2XL enhancement started');

      // Disable button and show spinner
      btn.disabled = true;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

      fetch('/api/magic_query_2xl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_text: text })
      })
        .then(res => {
          console.log('Magic 2XL API response received');
          return res.json();
        })
        .then(data => {
          console.log('Magic 2XL API data processed');
          if (data.error) {
            console.error('Magic query 2XL error:', data.error);
            ChatHelpers.addBotMessage('Error: ' + data.error);
          } else {
            const input = document.getElementById('query-input');
            input.value = data.output;
            // Store the enhanced flag as a data attribute on the input element
            if (data.is_enhanced) {
              input.dataset.enhanced = 'true';
              console.log('Query enhanced with magic wand 2XL');
            }
          }
        })
        .catch(error => {
          console.error('Network error during magic query 2XL:', error);
          ChatHelpers.addBotMessage('Network error: ' + error.message);
        })
        .finally(() => {
          // Ensure button state is restored regardless of success or failure
          console.log('Magic 2XL enhancement completed, restoring button state');

          // Use setTimeout to ensure this runs after all other callbacks
          setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = origIcon;
            console.log('Button state restored');
            // Hide mobile status indicator when enhancement completes
            if (window.mobileStatusHelpers) {
              window.mobileStatusHelpers.success('Prompt created!');
            }
          }, 0);
        });
    });
  }
  */
});

// Also try to initialize after a short delay in case the DOM is already loaded
setTimeout(function () {
  console.log('Delayed initialization of DevEvalChat');
  if (!DevEvalChat.initialized) {
    DevEvalChat.init();
  }
}, 1000);

// Add a global function to manually toggle eVal mode
// This can be called from the console for debugging
window.toggleDevMode = function () {
  console.log('Manual toggle of eVal mode');
  window.isDeveloperMode = !window.isDeveloperMode;
  console.log('isDeveloperMode set to:', window.isDeveloperMode);

  // Update UI based on the new mode
  if (window.isDeveloperMode) {
    DevEvalChat.currentState = DevEvalChat.STATE.QUERY;
    if (DevEvalChat.queryInput) {
      DevEvalChat.queryInput.placeholder = "Enter your query...";
    }
    if (DevEvalChat.devModeBtn) {
      DevEvalChat.devModeBtn.classList.add('bg-green-600', 'hover:bg-green-700');
      DevEvalChat.devModeBtn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
      DevEvalChat.devModeBtn.textContent = 'eVal mode: ON';
    }
    ChatHelpers.addBotMessage("Developer Evaluation mode enabled. Please enter your query for developer analysis.");
  } else {
    DevEvalChat.currentState = DevEvalChat.STATE.IDLE;
    if (DevEvalChat.queryInput) {
      DevEvalChat.queryInput.placeholder = "Ask me anything about our knowledge base...";
    }
    if (DevEvalChat.devModeBtn) {
      DevEvalChat.devModeBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
      DevEvalChat.devModeBtn.classList.add('bg-indigo-600', 'hover:bg-indigo-700');
      DevEvalChat.devModeBtn.textContent = 'eVal mode';
    }
    ChatHelpers.addBotMessage("Standard chat mode enabled.");
  }
};
