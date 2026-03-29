import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const fxiosEntryBootstrap = (): Plugin => ({
  name: "fxios-entry-bootstrap",
  apply: "build",
  transformIndexHtml: {
    order: "post",
    handler(html, ctx) {
      const bundle = ctx.bundle;
      if (!bundle) {
        return html;
      }
      let esmEntry = "";
      let cssHref = "";
      for (const item of Object.values(bundle)) {
        if (
          item.type === "chunk" &&
          item.isEntry &&
          item.fileName.endsWith(".js")
        ) {
          esmEntry = `/${item.fileName}`;
        }
        if (item.type === "asset" && item.fileName.endsWith(".css")) {
          cssHref = `/${item.fileName}`;
        }
      }
      if (!esmEntry) {
        return html;
      }
      const esmJson = JSON.stringify(esmEntry);
      const cssJson = JSON.stringify(cssHref);
      const bootstrap = `<script>(function(){function boot(){var u=navigator.userAgent||"";var fx=/FxiOS/i.test(u)||(/(iPhone|iPad|iPod)/.test(u)&&/Firefox/i.test(u)&&/AppleWebKit/i.test(u));var esm=${esmJson};var css=${cssJson};var prod=typeof esm==="string"&&esm.indexOf("/assets/")===0;var hd=document.head;if(!hd){return;}if(fx&&prod){if(css){var prev=hd.querySelector('link[rel="stylesheet"][href="'+css+'"]');if(prev){prev.remove();}}var s=document.createElement("script");s.defer=true;s.src="/assets/draft-gap-fxios.js";hd.appendChild(s);return;}var m=document.createElement("script");m.type="module";m.src=esm;hd.appendChild(m);}if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",boot);}else{boot();}})();</script>`;
      const modA =
        /<script\s+type="module"\s+src="[^"]+"\s*>\s*<\/script>/i;
      const modB =
        /<script\s+src="[^"]+"\s+type="module"\s*>\s*<\/script>/i;
      if (modA.test(html)) {
        return html.replace(modA, bootstrap);
      }
      if (modB.test(html)) {
        return html.replace(modB, bootstrap);
      }
      return html;
    },
  },
});

const stripBundleCrossorigin = () => ({
  name: "strip-bundle-crossorigin",
  apply: "build" as const,
  enforce: "post" as const,
  transformIndexHtml(html: string) {
    return html
      .replace(
        /(<script\b[^>]*\btype=["']module["'])\s+crossorigin/gi,
        "$1",
      )
      .replace(
        /(<link\b[^>]*\brel=["']stylesheet["'])\s+crossorigin/gi,
        "$1",
      )
      .replace(
        /(<link\b[^>]*\brel=["']modulepreload["'])\s+crossorigin/gi,
        "$1",
      );
  },
});

export default defineConfig({
  plugins: [react(), stripBundleCrossorigin(), fxiosEntryBootstrap()],
  build: {
    target: ["es2020", "firefox90", "safari15", "chrome90", "ios15"],
    cssTarget: "safari14",
    minify: "terser",
  },
  preview: {
    allowedHosts: ["draft-gap.sayarin.xyz"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
