/**
 * Debug Logger Module
 * Provides logging functionality for debugging the dynamic container and citation toggle
 */

(function() {
  class DebugLogger {
    constructor() {
      this.enabled = true;
      this.logToConsole = true;
      this.logToUI = true;
      this.maxLogs = 100;
      this.logs = [];
      
      // Initialize the logger
      this.init();
    }
    
    init() {
      console.log('Debug Logger initialized');
      
      // Check if we have a UI container for logs
      this.uiContainer = window.logsContainer || null;
      
      // Add keyboard shortcut to toggle logging (Ctrl+Alt+D)
      document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.altKey && e.key === 'd') {
          this.toggleLogging();
        }
      });
    }
    
    toggleLogging() {
      this.enabled = !this.enabled;
      this.log(`Logging ${this.enabled ? 'enabled' : 'disabled'}`, 'system');
    }
    
    log(message, category = 'general', data = null) {
      if (!this.enabled) return;
      
      const timestamp = new Date().toISOString();
      const logEntry = {
        timestamp,
        message,
        category,
        data
      };
      
      // Add to logs array
      this.logs.push(logEntry);
      
      // Trim logs if needed
      if (this.logs.length > this.maxLogs) {
        this.logs.shift();
      }
      
      // Log to console if enabled
      if (this.logToConsole) {
        const consoleMessage = `[${category}] ${message}`;
        if (data) {
          console.log(consoleMessage, data);
        } else {
          console.log(consoleMessage);
        }
      }
      
      // Log to UI if enabled and container exists
      if (this.logToUI && this.uiContainer) {
        this.addLogToUI(logEntry);
      }
    }
    
    addLogToUI(logEntry) {
      const logElement = document.createElement('div');
      logElement.className = 'log-entry mb-2 pb-2 border-b border-gray-200';
      
      // Format timestamp
      const date = new Date(logEntry.timestamp);
      const formattedTime = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      
      // Set category color
      let categoryColor = 'text-gray-500';
      switch (logEntry.category) {
        case 'error':
          categoryColor = 'text-red-500';
          break;
        case 'warning':
          categoryColor = 'text-yellow-500';
          break;
        case 'success':
          categoryColor = 'text-green-500';
          break;
        case 'system':
          categoryColor = 'text-blue-500';
          break;
        case 'user-action':
          categoryColor = 'text-purple-500';
          break;
        case 'ui-state':
          categoryColor = 'text-blue-700';
          break;
        case 'user-preference':
          categoryColor = 'text-pink-500';
          break;
      }
      
      // Create log content
      logElement.innerHTML = `
        <div class="flex items-start">
          <span class="text-xs text-gray-400 mr-2">${formattedTime}</span>
          <span class="text-xs ${categoryColor} font-medium mr-2">[${logEntry.category}]</span>
          <span class="text-xs text-gray-800">${logEntry.message}</span>
        </div>
        ${logEntry.data ? `
          <div class="mt-1 ml-4">
            <pre class="text-xs bg-gray-100 p-1 rounded overflow-x-auto">${JSON.stringify(logEntry.data, null, 2)}</pre>
          </div>
        ` : ''}
      `;
      
      // Add to UI container
      this.uiContainer.insertBefore(logElement, this.uiContainer.firstChild);
    }
    
    clearLogs() {
      this.logs = [];
      if (this.uiContainer) {
        this.uiContainer.innerHTML = '';
      }
      this.log('Logs cleared', 'system');
    }
    
    getLogs(category = null) {
      if (category) {
        return this.logs.filter(log => log.category === category);
      }
      return this.logs;
    }
  }
  
  // Create a global instance of the logger
  window.debugLogger = new DebugLogger();
})();
