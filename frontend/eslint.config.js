import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// 只开「会抓到真 bug」的规则，不做风格重写。
//
// 类型层面的检查已经由 `tsc --noEmit`（strict + noUnusedLocals +
// noUnusedParameters）覆盖，所以这里不重复开类型感知规则 —— 那会让 lint 慢一个
// 数量级，而收益是同一批错误报两遍。这里补的是 tsc 看不到的两类：
//   - react-hooks 的调用顺序与依赖数组；
//   - 未使用变量在 .tsx 里被 JSX 掩盖的情况。
export default tseslint.config(
  {
    ignores: ["dist", "node_modules", "test-results", "playwright-report"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // 下划线前缀是「我知道它没用，但签名要求它」的约定。
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      "no-empty": "error",
      "prefer-const": "error",
      "no-useless-escape": "error",
      "@typescript-eslint/no-empty-object-type": "error",
      "@typescript-eslint/no-unused-expressions": "error",
      "no-loss-of-precision": "error",
    },
  },
);
