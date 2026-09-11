/* Diagram artifact preview boundary. No provider data or raw model reasoning belongs here. */
(function installDiagramPreview(global) {
  function createPreview({ url, title = "Diagram artifact", alt = title } = {}) {
    const figure = document.createElement("figure");
    figure.className = "diagram-artifact-preview";
    const image = document.createElement("img");
    image.src = String(url || "");
    image.alt = String(alt || title);
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    figure.appendChild(image);
    const caption = document.createElement("figcaption");
    caption.textContent = String(title);
    figure.appendChild(caption);
    return figure;
  }

  global.SudarshanDiagramPreview = Object.freeze({ createPreview });
})(window);
