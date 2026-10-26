import { cn } from "../../../lib/utils";
import { safeHref } from "../../../lib/safeHref";
import { CodeBlock } from "./CodeBlock";
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
const markdownComponents = {
    code({ className, children, ...props }: {
        className?: string;
        children?: React.ReactNode;
    }) {
        const match = /language-(\w+)/.exec(className || '');
        const codeStr = String(children).replace(/\n$/, '');
        if (match) {
            return <CodeBlock language={match[1]} code={codeStr}/>;
        }
        return (<code className="bg-ink/5 px-1.5 py-0.5 rounded-label text-[13px]" {...props}>
        {children}
      </code>);
    },
    table({ children }: {
        children?: React.ReactNode;
    }) {
        return (<div className="overflow-x-auto my-2">
        <table className="w-full text-xs border-collapse">{children}</table>
      </div>);
    },
    th({ children }: {
        children?: React.ReactNode;
    }) {
        return (<th className="px-3 py-2 text-left font-semibold bg-ink/[0.03] border-b border-stroke/60">
        {children}
      </th>);
    },
    td({ children }: {
        children?: React.ReactNode;
    }) {
        return <td className="px-3 py-2 border-b border-stroke/60">{children}</td>;
    },
};
export const Markdown: React.FC<{
    content: string;
    streaming?: boolean;
    className?: string;
}> = ({ content, streaming, className, }) => {
    const components = React.useMemo(() => ({
        ...markdownComponents,
        a({ href, children }: {
            href?: string;
            children?: React.ReactNode;
        }) {
            const hrefSafe = safeHref(href);
            if (!hrefSafe) {
                return <span className="text-ink-secondary">{children}</span>;
            }
            const isHash = hrefSafe.startsWith('#');
            return (<a href={hrefSafe} {...(isHash ? {} : { target: '_blank', rel: 'noopener noreferrer' })}>
          {children}
        </a>);
        },
    }), []);
    return (<div className={cn('prose-sm max-w-none text-sm leading-relaxed markdown-content min-w-0', streaming && 'is-streaming', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>);
};
