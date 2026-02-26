// Test script for base64 URL decoder

import { base64UrlExamples } from './base64_url_examples.js';
// Removed import of url-decoder.js because it is a classic script attaching to window
// Use window.urlDecoder directly

function testBase64UrlDecoder() {
  console.log('Starting Base64 URL Decoder Tests...\n');

  base64UrlExamples.forEach((example, index) => {
    const { description, base64 } = example;

    // Decode and clean URL
    const { raw, cleaned } = window.urlDecoder.decodeAndCleanUrl(base64);

    // Create download link and get success status
    const result = window.urlDecoder.createDownloadLink(base64, true);

    console.log(`Test #${index + 1}: ${description}`);
    console.log(`Base64 Input: ${base64}`);
    console.log(`Raw Decoded String: ${raw}`);
    console.log(`Cleaned URL: ${cleaned}`);
    console.log(`Decoding Successful: ${result.success}`);
    if (!result.success) {
      console.log(`Error: ${result.error}`);
    }
    console.log('----------------------------------------\n');
  });

  console.log('Base64 URL Decoder Tests Completed.');
}

// Run the test
testBase64UrlDecoder();