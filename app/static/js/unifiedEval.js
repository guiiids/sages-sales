(function() {
  // Add defensive function for string operations
  function safeReplace(str, pattern, replacement) {
    if (typeof str !== 'string') {
      console.warn('Attempted to replace on non-string:', str);
      return str || '';
    }
    return str.replace(pattern, replacement);
  }

  // Check if environment is compatible
  if (!isCompatible()) {
    console.warn('Unified Dev Eval: Environment not compatible, module disabled');
    return; // Exit without modifying anything
  }
  
  // Initialize only when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }
  
  function isCompatible() {
    // Check for required DOM elements and browser features
    const requiredElements = [
      'query-input', 
      'submit-btn', 
      'chat-messages'
    ];
    
    return requiredElements.every(id => document.getElementById(id)) &&
           typeof fetch === 'function' &&
           typeof localStorage === 'object';
  }
  
  function initialize() {
    console.log('Initializing Unified Dev Eval module...');
    
    // Load sub-modules
    const state = createStateManager();
    console.log('State manager created:', state);
    
    const ui = createUIManager(state);
    console.log('UI manager created:', ui);
    
    const api = createAPIManager(state, ui);
    console.log('API manager created:', api);
    
    // Create mode toggle buttons
    if (ui && typeof ui.createModeToggles === 'function') {
      ui.createModeToggles();
    } else {
      console.error('UI manager missing createModeToggles method');
    }
    
    // Hook into existing functionality
    hookIntoExistingFunctionality(state, ui, api);
    
    console.log('Unified Dev Eval: Successfully initialized');
  }
  
  // Sub-module factories
  function createStateManager() {
    // Constants
    const MODES = {
      DEVELOPER: 'developer',
      BATCH: 'batch',
      COMPARE: 'compare'
    };
    
    // State
    let activeMode = null;
    let currentStep = 'idle';
    let query = '';
    let prompt1 = '';
    let prompt2 = '';
    let parameters = {
      batch1: {
        temperature: 0.3,
        top_p: 1.0,
        max_tokens: 1000,
        runs: 1
      },
      batch2: {
        temperature: 0.3,
        top_p: 1.0,
        max_tokens: 1000,
        runs: 1
      }
    };
    let results = {};
    
    // Load saved parameters from localStorage if available
    try {
      const savedParams = localStorage.getItem('unifiedDevEvalParams');
      if (savedParams) {
        const parsed = JSON.parse(savedParams);
        if (parsed && typeof parsed === 'object') {
          parameters = parsed;
        }
      }
    } catch (e) {
      console.warn('Failed to load saved parameters:', e);
    }
    
    return {
      MODES,
      
      activateMode(mode) {
        console.log(`Activating mode: ${mode}`);
        activeMode = mode;
        currentStep = 'query';
        return this.getNextPrompt();
      },
      
      deactivateMode() {
        activeMode = null;
        currentStep = 'idle';
      },
      
      isModuleActive() {
        return activeMode !== null;
      },
      
      getCurrentMode() {
        return activeMode;
      },
      
      handleSubmit() {
        const queryInput = document.getElementById('query-input');
        if (!queryInput) return false;
        
        const userInput = queryInput.value.trim();
        
        // Process input based on current state and active mode
        this.handleUserInput(userInput);
        return true;
      },
      
      handleUserInput(input) {
        // Add user message to chat (only if input is not empty)
        if (input && window.addUserMessage) {
          window.addUserMessage(input);
        }
        
        const queryInput = document.getElementById('query-input');
        if (queryInput) {
          queryInput.value = '';
        }
        
        // Process input based on current step and active mode
        switch (currentStep) {
          case 'query':
            // Query cannot be empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage("Please enter a query to continue:");
              }
              return; // Stay on this step
            }
            query = input;
            currentStep = 'prompt_1';
            break;
          case 'prompt_1':
            // Prompt can be empty (use default)
            prompt1 = input; // Empty is fine here
            if (!input && window.addBotMessage) {
              window.addBotMessage("Using default prompt for Batch 1");
            }
            currentStep = 'temperature_1';
            break;
          case 'temperature_1':
            // Use default temperature if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default temperature: ${parameters.batch1.temperature}`);
              }
              // Keep default value
            } else {
              // Validate temperature
              let temp = parseFloat(input);
              if (isNaN(temp) || temp < 0 || temp > 2) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid temperature value. Please enter a number between 0.0 and 2.0:");
                }
                return; // Stay on this step
              }
              parameters.batch1.temperature = temp;
            }
            currentStep = 'top_p_1';
            break;
          case 'top_p_1':
            // Use default top_p if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default top_p: ${parameters.batch1.top_p}`);
              }
              // Keep default value
            } else {
              // Validate top_p input
              let topP = parseFloat(input);
              if (isNaN(topP) || topP < 0 || topP > 1) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid top_p value. Please enter a number between 0.0 and 1.0:");
                }
                return; // Stay on this step
              }
              parameters.batch1.top_p = topP;
            }
            currentStep = 'max_tokens_1'; // Move to next step
            break;
          case 'max_tokens_1':
            // Use default max_tokens if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default max_tokens: ${parameters.batch1.max_tokens}`);
              }
              // Keep default value
            } else {
              // Validate max_tokens input
              let maxTokens = parseInt(input);
              if (isNaN(maxTokens) || maxTokens < 1 || maxTokens > 4000) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid max_tokens value. Please enter a number between 1 and 4000:");
                }
                return; // Stay on this step
              }
              parameters.batch1.max_tokens = maxTokens;
            }
            
            // For developer mode, we're done collecting parameters
            if (activeMode === MODES.DEVELOPER) {
              this.processEvaluation();
              currentStep = 'processing';
              return;
            }
            
            // For batch and compare modes, ask for number of runs
            currentStep = 'runs_1';
            break;
          case 'runs_1':
            // Use default runs if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default runs: ${parameters.batch1.runs}`);
              }
              // Keep default value
            } else {
              // Validate runs input
              let runs = parseInt(input);
              if (isNaN(runs) || runs < 1 || runs > 20) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid number of runs. Please enter a number between 1 and 20:");
                }
                return; // Stay on this step
              }
              parameters.batch1.runs = runs;
            }
            
            // For batch mode, we're done collecting parameters
            if (activeMode === MODES.BATCH) {
              this.processEvaluation();
              currentStep = 'processing';
              return;
            }
            
            // For compare mode, continue to batch 2 parameters
            currentStep = 'prompt_2';
            break;
          case 'prompt_2':
            // Prompt can be empty (use default)
            prompt2 = input; // Empty is fine here
            if (!input && window.addBotMessage) {
              window.addBotMessage("Using default prompt for Batch 2");
            }
            currentStep = 'temperature_2';
            break;
          case 'temperature_2':
            // Use default temperature if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default temperature for Batch 2: ${parameters.batch2.temperature}`);
              }
              // Keep default value
            } else {
              // Validate temperature for batch 2
              let temp2 = parseFloat(input);
              if (isNaN(temp2) || temp2 < 0 || temp2 > 2) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid temperature value. Please enter a number between 0.0 and 2.0:");
                }
                return; // Stay on this step
              }
              parameters.batch2.temperature = temp2;
            }
            currentStep = 'top_p_2';
            break;
          case 'top_p_2':
            // Use default top_p if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default top_p for Batch 2: ${parameters.batch2.top_p}`);
              }
              // Keep default value
            } else {
              // Validate top_p input for batch 2
              let topP2 = parseFloat(input);
              if (isNaN(topP2) || topP2 < 0 || topP2 > 1) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid top_p value. Please enter a number between 0.0 and 1.0:");
                }
                return; // Stay on this step
              }
              parameters.batch2.top_p = topP2;
            }
            currentStep = 'max_tokens_2';
            break;
          case 'max_tokens_2':
            // Use default max_tokens if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default max_tokens for Batch 2: ${parameters.batch2.max_tokens}`);
              }
              // Keep default value
            } else {
              // Validate max_tokens input for batch 2
              let maxTokens2 = parseInt(input);
              if (isNaN(maxTokens2) || maxTokens2 < 1 || maxTokens2 > 4000) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid max_tokens value. Please enter a number between 1 and 4000:");
                }
                return; // Stay on this step
              }
              parameters.batch2.max_tokens = maxTokens2;
            }
            currentStep = 'runs_2';
            break;
          case 'runs_2':
            // Use default runs if input is empty
            if (!input) {
              if (window.addBotMessage) {
                window.addBotMessage(`Using default runs for Batch 2: ${parameters.batch2.runs}`);
              }
              // Keep default value
            } else {
              // Validate runs input for batch 2
              let runs2 = parseInt(input);
              if (isNaN(runs2) || runs2 < 1 || runs2 > 20) {
                if (window.addBotMessage) {
                  window.addBotMessage("Invalid number of runs. Please enter a number between 1 and 20:");
                }
                return; // Stay on this step
              }
              parameters.batch2.runs = runs2;
            }
            
            // For compare mode, we're done collecting parameters
            this.processEvaluation();
            currentStep = 'processing';
            return;
          default:
            console.warn(`Unknown step: ${currentStep}`);
        }
        
        // Show next prompt
        const nextPrompt = this.getNextPrompt();
        if (nextPrompt && window.addBotMessage) {
          window.addBotMessage(nextPrompt);
        }
      },
      
      getNextPrompt() {
        switch (currentStep) {
          case 'query':
            return "Please enter your query:";
          case 'prompt_1':
            return "Enter prompt/instructions for Batch 1 (or leave blank for default):";
          case 'temperature_1':
            return `Set temperature (0.0-2.0) (default ${parameters.batch1.temperature}):`;
          case 'top_p_1':
            return `Set top_p (0.0-1.0) (default ${parameters.batch1.top_p}):`;
          case 'max_tokens_1':
            return `Set max_tokens (1-4000) (default ${parameters.batch1.max_tokens}):`;
          case 'runs_1':
            return `How many times would you like to run this query? (1-20, default: ${parameters.batch1.runs})`;
          case 'prompt_2':
            return "Enter prompt/instructions for Batch 2 (or leave blank for default):";
          case 'temperature_2':
            return `Set temperature for Batch 2 (0.0-2.0) (default ${parameters.batch2.temperature}):`;
          case 'top_p_2':
            return `Set top_p for Batch 2 (0.0-1.0) (default ${parameters.batch2.top_p}):`;
          case 'max_tokens_2':
            return `Set max_tokens for Batch 2 (1-4000) (default ${parameters.batch2.max_tokens}):`;
          case 'runs_2':
            return `How many times would you like to run Batch 2? (1-20, default: ${parameters.batch2.runs})`;
          case 'processing':
            return "Processing your request...";
          default:
            return null;
        }
      },
      
      processEvaluation() {
        if (window.addBotMessage) {
          window.addBotMessage("Processing evaluation with the following parameters:");
          
          let paramsDisplay = `
            <strong>Query:</strong> ${window.escapeHtml ? window.escapeHtml(query) : query}<br>
            <strong>Parameters:</strong><br>
            - Temperature: ${parameters.batch1.temperature}<br>
            - Top P: ${parameters.batch1.top_p}<br>
            - Max Tokens: ${parameters.batch1.max_tokens}<br>
          `;
          
          if (activeMode !== MODES.DEVELOPER) {
            paramsDisplay += `- Runs: ${parameters.batch1.runs}<br>`;
          }
          
          if (prompt1) {
            paramsDisplay += `<strong>Custom Prompt for Batch 1:</strong> ${window.escapeHtml ? window.escapeHtml(prompt1) : prompt1}<br>`;
          }
          
          if (activeMode === MODES.COMPARE) {
            paramsDisplay += `
              <br><strong>Batch 2 Parameters:</strong><br>
              - Temperature: ${parameters.batch2.temperature}<br>
              - Top P: ${parameters.batch2.top_p}<br>
              - Max Tokens: ${parameters.batch2.max_tokens}<br>
              - Runs: ${parameters.batch2.runs}<br>
            `;
            
            if (prompt2) {
              paramsDisplay += `<strong>Custom Prompt for Batch 2:</strong> ${window.escapeHtml ? window.escapeHtml(prompt2) : prompt2}<br>`;
            }
          }
          
          window.addBotMessage(paramsDisplay);
        }
        
        // Show typing indicator
        const typingIndicator = window.addTypingIndicator ? window.addTypingIndicator() : null;
        
        // Prepare data for API call
        const data = {
          query: query,
          prompt: prompt1,
          parameters: {
            temperature: parameters.batch1.temperature,
            top_p: parameters.batch1.top_p,
            max_tokens: parameters.batch1.max_tokens
          }
        };
        
        if (activeMode !== MODES.DEVELOPER) {
          data.runs = parameters.batch1.runs;
        }
        
        if (activeMode === MODES.COMPARE) {
          data.batch2 = {
            temperature: parameters.batch2.temperature,
            top_p: parameters.batch2.top_p,
            max_tokens: parameters.batch2.max_tokens,
            runs: parameters.batch2.runs,
            prompt: prompt2 // Add separate prompt for batch 2
          };
        }
        
        // Call API based on mode
        let endpoint = '/api/query';
        switch (activeMode) {
          case MODES.DEVELOPER:
            endpoint = '/api/dev_eval';
            break;
          case MODES.BATCH:
            endpoint = '/api/dev_eval_batch';
            break;
          case MODES.COMPARE:
            endpoint = '/api/dev_eval_compare';
            break;
        }
        
        // Generate unique request ID for tracking
        const requestStartTime = Date.now();
        const requestId = `req_${requestStartTime}_${Math.random().toString(36).substr(2, 9)}`;
        
        // Log comprehensive API request details
        if (window.debugLogger) {
          window.debugLogger.log(`🚀 API Request Started`, 'api-request', {
            requestId: requestId,
            endpoint: endpoint,
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            payload: data,
            payloadSize: JSON.stringify(data).length,
            timestamp: new Date().toISOString(),
            mode: activeMode,
            userAgent: navigator.userAgent
          });
        }
        
        // Console logging for detailed debugging
        console.group(`🚀 [API REQUEST ${requestId}] Starting request to ${endpoint}`);
        console.log('📤 Request Details:', {
          endpoint: endpoint,
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          timestamp: new Date().toISOString(),
          mode: activeMode
        });
        console.log('📦 Request Payload:', JSON.stringify(data, null, 2));
        console.log('📏 Payload Size:', JSON.stringify(data).length, 'bytes');
        console.groupEnd();
        
        // Make API call with comprehensive logging
        fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        })
        .then(response => {
          const requestEndTime = Date.now();
          const duration = requestEndTime - requestStartTime;
          
          // Extract response headers
          const responseHeaders = {};
          for (let [key, value] of response.headers.entries()) {
            responseHeaders[key] = value;
          }
          
          // Log response details
          if (window.debugLogger) {
            window.debugLogger.log(`📥 API Response Received`, 'api-response', {
              requestId: requestId,
              status: response.status,
              statusText: response.statusText,
              headers: responseHeaders,
              duration: `${duration}ms`,
              timestamp: new Date().toISOString(),
              ok: response.ok,
              redirected: response.redirected,
              type: response.type,
              url: response.url
            });
          }
          
          console.group(`📥 [API RESPONSE ${requestId}] Response received`);
          console.log('📊 Response Status:', response.status, response.statusText);
          console.log('⏱️ Duration:', duration + 'ms');
          console.log('📋 Response Headers:', responseHeaders);
          console.log('✅ Response OK:', response.ok);
          console.log('🔄 Redirected:', response.redirected);
          console.log('📍 Response URL:', response.url);
          console.groupEnd();
          
          if (!response.ok) {
            const error = new Error(`HTTP error! Status: ${response.status} ${response.statusText}`);
            error.status = response.status;
            error.statusText = response.statusText;
            error.headers = responseHeaders;
            throw error;
          }
          return response.json();
        })
        .then(result => {
          const parseEndTime = Date.now();
          const totalDuration = parseEndTime - requestStartTime;
          
          // Log the complete response body
          if (window.debugLogger) {
            window.debugLogger.log(`📄 API Response Body Parsed`, 'api-response', {
              requestId: requestId,
              responseBody: result,
              responseSize: JSON.stringify(result).length,
              totalDuration: `${totalDuration}ms`,
              timestamp: new Date().toISOString(),
              hasError: !!result.error,
              hasResults: !!(result.result || result.answer || result.results || result.batch1_results),
              hasSources: !!(result.sources && result.sources.length > 0)
            });
          }
          
          console.group(`📄 [API RESPONSE ${requestId}] Response body parsed`);
          console.log('📦 Response Body:', JSON.stringify(result, null, 2));
          console.log('📏 Response Size:', JSON.stringify(result).length, 'bytes');
          console.log('⏱️ Total Duration:', totalDuration + 'ms');
          console.log('❌ Has Error:', !!result.error);
          console.log('✅ Has Results:', !!(result.result || result.answer || result.results || result.batch1_results));
          console.log('📚 Has Sources:', !!(result.sources && result.sources.length > 0));
          if (result.error) {
            console.error('❌ API Error:', result.error);
          }
          console.groupEnd();
          
          // Remove typing indicator
          if (typingIndicator && typingIndicator.remove) {
            typingIndicator.remove();
          }
          
          // Display result based on mode
          if (window.addBotMessage) {
            if (result.error) {
              window.addBotMessage(`<strong>Error:</strong> ${result.error}`);
            } else {
              // Handle different response formats based on mode
              if (activeMode === MODES.COMPARE) {
                // For compare mode, handle batch1_results and batch2_results
                window.addBotMessage(`<strong>LLM Output:</strong>`);
                
                // Display Batch 1 Results
                if (result.batch1_results && result.batch1_results.length > 0) {
                  window.addBotMessage(`<strong>Batch 1 Results:</strong>`);
                  result.batch1_results.forEach((item, index) => {
                    let answer = '';
                    if (item.answer) {
                      answer = item.answer;
                    } else if (item.result) {
                      answer = item.result;
                    } else if (typeof item === 'string') {
                      answer = item;
                    }
                    
                    if (answer) {
                      if (window.formatMessage && typeof answer === 'string') {
                        answer = window.formatMessage(answer);
                      }
                      window.addBotMessage(`<strong>Run ${index + 1}:</strong><br>${answer}`);
                    }
                  });
                }
                
                // Display Batch 2 Results
                if (result.batch2_results && result.batch2_results.length > 0) {
                  window.addBotMessage(`<strong>Batch 2 Results:</strong>`);
                  result.batch2_results.forEach((item, index) => {
                    let answer = '';
                    if (item.answer) {
                      answer = item.answer;
                    } else if (item.result) {
                      answer = item.result;
                    } else if (typeof item === 'string') {
                      answer = item;
                    }
                    
                    if (answer) {
                      if (window.formatMessage && typeof answer === 'string') {
                        answer = window.formatMessage(answer);
                      }
                      window.addBotMessage(`<strong>Run ${index + 1}:</strong><br>${answer}`);
                    }
                  });
                }
              } else if (activeMode === MODES.BATCH) {
                // For batch mode, handle results array
                window.addBotMessage(`<strong>LLM Output:</strong>`);
                
                if (result.results && result.results.length > 0) {
                  result.results.forEach((item, index) => {
                    let answer = '';
                    if (item.answer) {
                      answer = item.answer;
                    } else if (item.result) {
                      answer = item.result;
                    } else if (typeof item === 'string') {
                      answer = item;
                    }
                    
                    if (answer) {
                      if (window.formatMessage && typeof answer === 'string') {
                        answer = window.formatMessage(answer);
                      }
                      window.addBotMessage(`<strong>Run ${index + 1}:</strong><br>${answer}`);
                    }
                  });
                }
              } else {
                // For developer mode or other modes
                let formattedResult = '';
                
                // Try to extract the result from various possible formats
                if (result.result) {
                  formattedResult = result.result;
                } else if (result.answer) {
                  formattedResult = result.answer;
                } else if (result.results && result.results.length > 0) {
                  formattedResult = result.results.map(r => r.answer || r.result || '').join('<br><br>');
                } else if (result.batch1_results && result.batch1_results.length > 0) {
                  // Fallback for compare mode if not handled above
                  formattedResult = result.batch1_results.map(r => r.answer || r.result || '').join('<br><br>');
                }
                
                if (formattedResult) {
                  if (window.formatMessage && typeof formattedResult === 'string') {
                    formattedResult = window.formatMessage(formattedResult);
                  }
                  window.addBotMessage(`<strong>LLM Output:</strong><br>${formattedResult}`);
                }
              }
              
                // Display sources if available
              if (result.sources && result.sources.length > 0) {
                let sourcesText = '<strong>Sources:</strong><br><div class="sources-container">';
                result.sources.forEach((source, index) => {
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
                
                window.addBotMessage(sourcesText);
                
                // Add click event for citation links and toggle buttons
                setTimeout(() => {
                  // Handle citation links
                  document.querySelectorAll('.citation-link').forEach(link => {
                    link.addEventListener('click', function(e) {
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
                    btn.addEventListener('click', function() {
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
              
              // Display developer evaluation if available
              if (result.developer_evaluation) {
                let evalText = result.developer_evaluation;
                if (window.formatMessage && typeof evalText === 'string') {
                  evalText = window.formatMessage(evalText);
                }
                window.addBotMessage(`<strong>Developer Evaluation:</strong><br>${evalText}`);
              }
              
              // Display download links if available
              if (result.download_url_json || result.download_url_md) {
                let downloadLinks = '<strong>Report:</strong><br><div class="flex flex-wrap gap-2 mt-2">';
                
                if (result.download_url_json) {
                  downloadLinks += `<a href="${result.download_url_json}" download class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 inline-block">Download JSON</a>`;
                }
                
                if (result.download_url_md) {
                  downloadLinks += `<a href="${result.download_url_md}" download class="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 inline-block">Download Markdown</a>`;
                }
                
                if (result.markdown_report) {
                  downloadLinks += `<button id="view-in-console-btn" class="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 inline-block">View in Console</button>`;
                }
                
                downloadLinks += '</div>';
                window.addBotMessage(downloadLinks);
                
                // Add event listener for "View in Console" button
                setTimeout(() => {
                  const viewInConsoleBtn = document.getElementById('view-in-console-btn');
                  if (viewInConsoleBtn) {
                    viewInConsoleBtn.addEventListener('click', function() {
                      if (window.openDrawer) {
                        window.openDrawer();
                      }
                      
                      const logsContainer = window.logsContainer || document.getElementById('console-logs-content');
                      if (logsContainer && result.markdown_report) {
                        logsContainer.innerHTML = `<div class="p-4 bg-white dark:bg-black text-white rounded shadow" style="font-family: monospace; white-space: pre-wrap; font-size: 14px; line-height: 1.5;">${result.markdown_report}</div>`;
                      }
                    });
                  }
                }, 100);
              }
            }
          }
          
          // Reset for next query
          currentStep = 'query';
        })
        .catch(error => {
          const errorEndTime = Date.now();
          const errorDuration = errorEndTime - requestStartTime;
          
          // Log comprehensive error details
          if (window.debugLogger) {
            window.debugLogger.log(`❌ API Request Failed`, 'api-error', {
              requestId: requestId,
              error: error.message,
              status: error.status || 'unknown',
              statusText: error.statusText || 'unknown',
              headers: error.headers || {},
              duration: `${errorDuration}ms`,
              timestamp: new Date().toISOString(),
              stack: error.stack
            });
          }
          
          console.group(`❌ [API ERROR ${requestId}] Request failed`);
          console.error('💥 Error Message:', error.message);
          console.error('📊 Error Status:', error.status || 'unknown');
          console.error('📋 Error Headers:', error.headers || {});
          console.error('⏱️ Error Duration:', errorDuration + 'ms');
          console.error('🔍 Error Stack:', error.stack);
          console.groupEnd();
          
          // Remove typing indicator
          if (typingIndicator && typingIndicator.remove) {
            typingIndicator.remove();
          }
          
          // Display error
          if (window.addBotMessage) {
            window.addBotMessage(`<strong>Error:</strong> ${error.message}`);
          }
          
          console.error('API call failed:', error);
          
          // Reset for next query
          currentStep = 'query';
        });
      },
      
      saveParameters() {
        try {
          localStorage.setItem('unifiedDevEvalParams', JSON.stringify(parameters));
        } catch (e) {
          console.warn('Failed to save parameters:', e);
        }
      }
    };
  }
  
  function createUIManager(state) {
    if (!state) {
      console.error('State manager is required for UI manager');
      return null;
    }
    
    // Find or create mode buttons container
    const modeButtonsContainer = document.getElementById('mode-buttons-container') || 
                                 document.querySelector('.inline-flex.rounded-md');
    
    if (!modeButtonsContainer) {
      console.warn('Mode buttons container not found');
      return null;
    }
    
    return {
      createModeToggles() {
        console.log('Creating mode toggles...');
        
        // Get existing developer mode button
        const devModeBtn = document.getElementById('toggle-developer-mode-btn');
        
        // Create batch mode button if it doesn't exist
        let batchModeBtn = document.getElementById('toggle-batch-mode-btn');
        if (!batchModeBtn) {
          batchModeBtn = document.createElement('button');
          batchModeBtn.id = 'toggle-batch-mode-btn';
          batchModeBtn.className = 'mode-button ml-2 px-4 py-2 text-xs font-medium text-black border bg- rounded hover:bg-blue-200 focus:outline-none focus:ring-2 focus:ring-pink-500';
          batchModeBtn.textContent = 'reAsk Mode';
          batchModeBtn.setAttribute('data-created-by', 'unified-dev-eval');
          modeButtonsContainer.appendChild(batchModeBtn);
        }
        
        // Create compare mode button if it doesn't exist
        let compareModeBtn = document.getElementById('toggle-compare-mode-btn');
        if (!compareModeBtn) {
          compareModeBtn = document.createElement('button');
          compareModeBtn.id = 'toggle-compare-mode-btn';
          compareModeBtn.className = 'mode-button ml-2 px-4 py-2 text-xs font-medium text-black underline border bg-white dark:bg-black text-white rounded hover:bg-blue-200 focus:outline-none focus:ring-2 focus:ring-teal-500';
          compareModeBtn.textContent = 'sMash Mode';
          compareModeBtn.setAttribute('data-created-by', 'unified-dev-eval');
          modeButtonsContainer.appendChild(compareModeBtn);
        }
        
        // Add event listeners to mode buttons
        if (devModeBtn) {
          devModeBtn.addEventListener('click', () => this.toggleMode(state.MODES.DEVELOPER, devModeBtn));
        }
        
        if (batchModeBtn) {
          batchModeBtn.addEventListener('click', () => this.toggleMode(state.MODES.BATCH, batchModeBtn));
        }
        
        if (compareModeBtn) {
          compareModeBtn.addEventListener('click', () => this.toggleMode(state.MODES.COMPARE, compareModeBtn));
        }
        
        console.log('Mode toggles created');
      },
      
      toggleMode(mode, button) {
        console.log(`Toggling mode: ${mode}`);
        // Clear message board
        const messagesContainer = document.getElementById('chat-messages') || document.querySelector('.messages-container');
        if (messagesContainer) { messagesContainer.innerHTML = ''; }
        
        // Get all mode buttons
        const modeButtons = document.querySelectorAll('.mode-button');
        
        // If clicking the active mode button, deactivate it
        if (state.getCurrentMode() === mode) {
          // Deactivate mode
          state.deactivateMode();
          
          // Reset button styles
          modeButtons.forEach(btn => {
            btn.classList.remove('active');
            if (btn.id === 'toggle-developer-mode-btn') {
              btn.classList.remove('bg-green-600', 'hover:bg-green-700');
              btn.classList.add('bg-blue-600', 'hover:bg-indigo-700');
              btn.textContent = 'eVal Mode';
            } else if (btn.id === 'toggle-batch-mode-btn') {
              btn.textContent = 'reAsk Mode';
            } else if (btn.id === 'toggle-compare-mode-btn') {
              btn.textContent = 'sMash Mode';
            }
          });
          
          // Add message
          if (window.addBotMessage) {
            window.addBotMessage("Standard chat mode enabled.");
          }
        } else {
          // Deactivate all modes first
          state.deactivateMode();
          
          // Reset all button styles
          modeButtons.forEach(btn => {
            btn.classList.remove('active');
            if (btn.id === 'toggle-developer-mode-btn') {
              btn.classList.remove('bg-green-600', 'hover:bg-green-700');
              btn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
              btn.classList.add('bg-blue-600', 'hover:bg-indigo-700');
              btn.textContent = 'eVal Mode';
            } else if (btn.id === 'toggle-batch-mode-btn') {
              btn.textContent = 'reAsk Mode';
            } else if (btn.id === 'toggle-compare-mode-btn') {
              btn.textContent = 'sMash Mode';
            }
          });
          
          // Activate selected mode
          const welcomeMessage = state.activateMode(mode);
          
          // Update button style
          button.classList.add('active');
          if (button.id === 'toggle-developer-mode-btn') {
            button.classList.remove('bg-white', 'hover:bg-indigo-700');
            button.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
            button.classList.add('bg-blue-600', 'hover:bg-blue-200');
            button.textContent = 'eVal Mode: ON';
          } else if (button.id === 'toggle-batch-mode-btn') {
            button.textContent = 'reAsk Mode: ON';
          } else if (button.id === 'toggle-compare-mode-btn') {
            button.textContent = 'sMashe Mode: ON';
          }
          
          // Add welcome message
          if (window.addBotMessage && welcomeMessage) {
            window.addBotMessage(welcomeMessage);
          }
        }
      },
      
      removeAllCustomElements() {
        document.querySelectorAll('[data-created-by="unified-dev-eval"]').forEach(el => {
          el.remove();
        });
      }
    };
  }
  
  function createAPIManager(state, ui) {
    if (!state) {
      console.error('State manager is required for API manager');
      return null;
    }
    
    // Get API endpoints from config
    const endpoints = window.unifiedDevEvalConfig?.apiEndpoints || {
      developer: '/api/dev_eval',
      batch: '/api/dev_eval_batch',
      compare: '/api/dev_eval_compare'
    };
    
    return {
      processEvaluation(data, mode) {
        const endpoint = endpoints[mode] || '/api/query';
        
        return fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        })
        .then(response => response.json());
      }
    };
  }
  
  function hookIntoExistingFunctionality(state, ui, api) {
    // Store original functions
    const original = {
      submitQuery: window.submitQuery || function(){},
      addUserMessage: window.addUserMessage || function(){},
      addBotMessage: window.addBotMessage || function(){}
    };
    
    // Override submitQuery
    window.submitQuery = function() {
      if (state && state.isModuleActive()) {
        return state.handleSubmit();
      } else {
        return original.submitQuery.apply(this, arguments);
      }
    };
    
    // Add disable function for emergency fallback
    window.disableUnifiedDevEval = function() {
      // Restore original functions
      window.submitQuery = original.submitQuery;
      window.addUserMessage = original.addUserMessage;
      window.addBotMessage = original.addBotMessage;
      
      // Remove UI elements
      if (ui && typeof ui.removeAllCustomElements === 'function') {
        ui.removeAllCustomElements();
      }
      
      console.log('Unified Dev Eval: Module disabled');
      return true;
    };
    
    // Add event listener to submit button
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
      // Remove existing listeners to avoid duplicates
      const newBtn = submitBtn.cloneNode(true);
      submitBtn.parentNode.replaceChild(newBtn, submitBtn);
      
      // Add new listener
      newBtn.addEventListener('click', function() {
        window.submitQuery();
      });
    }
    
    // Add emergency disable button
    const emergencyBtn = document.createElement('button');
    emergencyBtn.id = 'emergency-disable-unified-dev-eval';
    emergencyBtn.className = 'px-4 py-2 bg-red-600 text-white rounded fixed bottom-4 right-4 z-50';
    emergencyBtn.textContent = 'Disable Unified Dev Eval';
    emergencyBtn.style.display = 'none'; // Hidden by default
    emergencyBtn.setAttribute('data-created-by', 'unified-dev-eval');
    
    emergencyBtn.addEventListener('click', function() {
      window.disableUnifiedDevEval();
      this.textContent = 'Unified Dev Eval Disabled';
      setTimeout(() => this.remove(), 3000);
    });
    
    document.body.appendChild(emergencyBtn);
    
    // Show button when errors occur
    window.addEventListener('error', function() {
      emergencyBtn.style.display = 'block';
    });
  }
})();
