import React from 'react';
import { TextMessagePartProvider } from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import remarkGfm from 'remark-gfm';

import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '../ui/table';
import { cn } from '../../lib/utils';
import { QueryCitationBadge } from './QueryCitationBadge';

const remarkPlugins = [remarkGfm];
const preprocessCitation = (text: string) => {
  let cleaned = text;
  // 1. Remove patterns like "数据来源：01_销售订单明细 [查询 Q...]" or "数据来源：[查询 Q...]"
  cleaned = cleaned.replace(/(?:，|。|；|,|;|\s)*(?:数据来源|数据依据|数据来源于)[：:][^，。；;\n\r]*?\[查询\s+[^\]]+\](?:\s*。)?/g, '。');
  // 2. Remove parenthetical citations like "（数据来源：[查询 Q...]）"
  cleaned = cleaned.replace(/[(（](?:数据来源|数据依据)[：:][^)]*?\[查询\s+[^\]]+\]\s*[)）]/g, '');
  // 3. Remove standalone "[查询 Q...]"
  cleaned = cleaned.replace(/\[查询\s+[^\]]+\]/g, '');
  // Clean up any double periods caused by replacement
  cleaned = cleaned.replace(/。+/g, '。');
  return cleaned;
};

const components = {
  table: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'table'> & { node?: unknown }) => (
    <div className="my-4 rounded-xl border border-border overflow-x-auto">
      <Table className={cn("w-full border-collapse text-sm", className)} {...props} />
    </div>
  ),
  thead: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'thead'> & { node?: unknown }) => (
    <TableHeader className={className} {...props} />
  ),
  tbody: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'tbody'> & { node?: unknown }) => (
    <TableBody className={className} {...props} />
  ),
  tr: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'tr'> & { node?: unknown }) => (
    <TableRow className={cn("border-b border-border transition-colors hover:bg-muted/40", className)} {...props} />
  ),
  th: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'th'> & { node?: unknown }) => (
    <TableHead
      className={cn(
        "h-9 px-3 py-2 text-left font-semibold text-foreground bg-muted/60 border border-border text-xs",
        className
      )}
      {...props}
    />
  ),
  td: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'td'> & { node?: unknown }) => (
    <TableCell
      className={cn(
        "px-3 py-2 text-left text-foreground border border-border text-xs min-w-[5rem]",
        className
      )}
      {...props}
    />
  ),
  a: ({ node, className, href, children, ...props }: React.ComponentPropsWithoutRef<'a'> & { node?: unknown }) => {
    if (href?.startsWith('#citation:')) {
      const citationId = href.replace('#citation:', '');
      return <QueryCitationBadge citationId={citationId} />;
    }
    return (
      <a {...props} href={href} target="_blank" rel="noopener noreferrer" className={cn("text-primary hover:underline underline-offset-2", className)}>
        {children}
      </a>
    );
  },
};

export function MarkdownText() {
  return <MarkdownTextPrimitive className="assistant-markdown" remarkPlugins={remarkPlugins}
    components={components} smooth={false} skipHtml preprocess={preprocessCitation} />;
}

export function MarkdownContent({ text, isRunning = false }: { text: string; isRunning?: boolean }) {
  return <TextMessagePartProvider text={text} isRunning={isRunning}><MarkdownText /></TextMessagePartProvider>;
}
