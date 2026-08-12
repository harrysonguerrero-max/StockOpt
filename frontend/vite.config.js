import { defineConfig } from "vite";

/* Vite aqui no impone framework: la interfaz sigue siendo HTML y modulos ES
 * nativos. Hace tres cosas que si hacen falta para publicar en Amplify:
 *
 *   1. Deja el resultado en `dist/`, que es lo que empaqueta y sube
 *      `deployment/aws-service-deployment.ps1`.
 *   2. Pone una huella en el nombre de cada archivo. Servido desde una CDN, un
 *      cambio invisible por cache no es una molestia sino un despliegue que
 *      parece no haber ocurrido.
 *   3. Resuelve la URL de la API desde el entorno, porque en Amplify la
 *      interfaz y la API viven en dominios distintos.
 */
export default defineConfig({
  // Rutas relativas: Amplify sirve la carpeta como raiz del sitio.
  base: "./",

  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },

  // En desarrollo la API se atraviesa por proxy, de modo que el navegador ve un
  // solo origen y no hay CORS que configurar en local.
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
