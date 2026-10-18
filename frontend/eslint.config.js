/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
// Lint rules for the frontend: TypeScript's recommended rules and the React Hooks rules
// (hooks called in the right order, effects with complete dependencies). Enforced in CI.
// Formatting is Prettier's job (`npm run format`), not ESLint's.

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", ".lighthouseci", "node_modules"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    // build and tooling scripts run in Node
    files: ["*.{js,cjs,mjs,ts}", "scripts/**/*.mjs", "lighthouse/**/*.cjs"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.node },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
);
