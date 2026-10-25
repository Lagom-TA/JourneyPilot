import React, { Suspense, lazy } from 'react';
const Highlighter = lazy(async () => {
    const [prismMod, styleMod, json, javascript, typescript, python, bash, yaml, markdown] = await Promise.all([
        import('react-syntax-highlighter/dist/esm/prism-light'),
        import('react-syntax-highlighter/dist/esm/styles/prism/one-light'),
        import('react-syntax-highlighter/dist/esm/languages/prism/json'),
        import('react-syntax-highlighter/dist/esm/languages/prism/javascript'),
        import('react-syntax-highlighter/dist/esm/languages/prism/typescript'),
        import('react-syntax-highlighter/dist/esm/languages/prism/python'),
        import('react-syntax-highlighter/dist/esm/languages/prism/bash'),
        import('react-syntax-highlighter/dist/esm/languages/prism/yaml'),
        import('react-syntax-highlighter/dist/esm/languages/prism/markdown'),
    ]);
    const PrismLight = prismMod.default;
    PrismLight.registerLanguage('json', json.default);
    PrismLight.registerLanguage('javascript', javascript.default);
    PrismLight.registerLanguage('typescript', typescript.default);
    PrismLight.registerLanguage('python', python.default);
    PrismLight.registerLanguage('bash', bash.default);
    PrismLight.registerLanguage('yaml', yaml.default);
    PrismLight.registerLanguage('markdown', markdown.default);
    const oneLight = styleMod.default;
    const Colored: React.FC<{
        language: string;
        code: string;
    }> = ({ language, code }) => (<PrismLight style={oneLight} language={language} PreTag="div" customStyle={{ borderRadius: '8px', fontSize: '13px', margin: '8px 0' }}>
      {code}
    </PrismLight>);
    return { default: Colored };
});
const CodeFallback: React.FC<{
    code: string;
}> = ({ code }) => (<pre className="overflow-x-auto rounded-card bg-ink/[0.03] p-3 text-[13px] leading-relaxed" style={{ margin: '8px 0' }}>
    <code>{code}</code>
  </pre>);
export const CodeBlock: React.FC<{
    language: string;
    code: string;
}> = ({ language, code }) => (<Suspense fallback={<CodeFallback code={code}/>}>
    <Highlighter language={language} code={code}/>
  </Suspense>);
