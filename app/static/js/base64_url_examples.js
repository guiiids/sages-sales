/**
 * A set of diverse Base64-encoded strings representing URLs to PDF, TXT, and CSV files.
 * Includes properly encoded URLs, malformed/truncated variants, extra/missing padding,
 * URL-encoded characters, and cases requiring fallback trimming logic.
 */

function polyfillBtoa(str) {
  if (typeof window !== "undefined" && typeof window.btoa === "function" && window.btoa !== polyfillBtoa) {
    return window.btoa(str);
  } else if (typeof Buffer !== "undefined") {
    return Buffer.from(str, 'binary').toString('base64');
  } else {
    throw new Error("No native btoa function available");
  }
}

function safeBtoa(str) {
  return polyfillBtoa(str);
}

const base64UrlExamples = [
  // Properly encoded full URLs ending with .pdf, .txt, or .csv
  {
    description: "Properly encoded full URL ending with .pdf",
    base64: safeBtoa("https://example.com/files/document.pdf")
  },
  {
    description: "Properly encoded full URL ending with .txt",
    base64: safeBtoa("https://example.com/files/readme.txt")
  },
  {
    description: "Properly encoded full URL ending with .csv",
    base64: safeBtoa("https://example.com/data/export.csv")
  },

  // URLs with trailing garbage characters after the file extension
  {
    description: "URL with trailing garbage character after .pdf (e.g., .pdf%)",
    base64: safeBtoa("https://example.com/files/document.pdf%")
  },
  {
    description: "URL with trailing garbage character after .pdf (e.g., .pdf5)",
    base64: safeBtoa("https://example.com/files/document.pdf5")
  },

  // Malformed Base64 strings (invalid characters)
  {
    description: "Base64 string with invalid characters inserted",
    base64: safeBtoa("https://example.com/files/document.pdf").slice(0, 10) + "!!??" + safeBtoa("https://example.com/files/document.pdf").slice(10)
  }
];

export { base64UrlExamples };