import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

const eslintConfig = defineConfig([
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  {
    files: ["src/app/components/Table/**/*.{ts,tsx}"],
    rules: {
      "react-hooks/incompatible-library": "off",
    },
  },
  globalIgnores([
    ".next/**",
    "dist/**",
    "build/**",
    "out/**",
    "coverage/**",
  ]),
]);

export default eslintConfig;
