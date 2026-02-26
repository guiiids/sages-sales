document.addEventListener('DOMContentLoaded', () => {
  const themeToggle = document.getElementById('theme-toggle');
  const html = document.documentElement;

  // Function to apply theme
  const applyTheme = (theme) => {
    if (theme === 'dark') {
      html.classList.add('dark');
      if (themeToggle) themeToggle.checked = true;
    } else {
      html.classList.remove('dark');
      if (themeToggle) themeToggle.checked = false;
    }
  };

  // Check for saved theme in localStorage
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme) {
    applyTheme(savedTheme);
  } else {
    // Check for system preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    applyTheme(prefersDark ? 'dark' : 'light');
  }

  // Add event listener for the toggle
  if (themeToggle) {
    themeToggle.addEventListener('change', () => {
      const newTheme = themeToggle.checked ? 'dark' : 'light';
      localStorage.setItem('theme', newTheme);
      applyTheme(newTheme);
    });
  }

  // Listen for changes in system preference
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    // Only change if no theme is saved in localStorage
    if (!localStorage.getItem('theme')) {
      applyTheme(e.matches ? 'dark' : 'light');
    }
  });
});
