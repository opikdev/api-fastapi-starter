const root = document.getElementById("swagger-ui");

window.ui = SwaggerUIBundle({
  url: root.dataset.openapiUrl,
  dom_id: "#swagger-ui",
  layout: "BaseLayout",
  deepLinking: true,
  showExtensions: true,
  showCommonExtensions: true,
  validatorUrl: null,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
});
