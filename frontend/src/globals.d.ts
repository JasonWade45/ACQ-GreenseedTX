/* Injected by vite.config.ts from package.json. */
declare const __APP_VERSION__: string;

// Set at build time by the hosting build (empty means "same origin as the API").
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
