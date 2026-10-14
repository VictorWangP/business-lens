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

const remarkPlugins = [remarkGfm];
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
  a: ({ node, className, ...props }: React.ComponentPropsWithoutRef<'a'> & { node?: unknown }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" className={cn("text-primary hover:underline underline-offset-2", className)} />
  ),
};

export function MarkdownText() {
  return <MarkdownTextPrimitive className="assistant-markdown" remarkPlugins={remarkPlugins}
    components={components} smooth={false} skipHtml />;
}

export function MarkdownContent({ text, isRunning = false }: { text: string; isRunning?: boolean }) {
  return <TextMessagePartProvider text={text} isRunning={isRunning}><MarkdownText /></TextMessagePartProvider>;
}
