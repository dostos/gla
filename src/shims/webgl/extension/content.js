// Inject the interceptor + trace scanner into the page context so they
// can access WebGLRenderingContext / WebGL2RenderingContext + window
// globals of the target page.
['interceptor.js', 'gpa-trace.js'].forEach(function (name) {
  const script = document.createElement('script');
  script.src = chrome.runtime.getURL(name);
  (document.head || document.documentElement).appendChild(script);
});
