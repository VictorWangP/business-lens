import { ThreadListPrimitive, ThreadListItemPrimitive } from '@assistant-ui/react';
import React, { useState, useRef, useEffect } from 'react';
import {
  Plus,
  MessageSquare,
  Trash2,
  PanelLeftClose,
  Pin,
  PinOff,
  Pencil,
  Check,
  X
} from 'lucide-react';
import { MoreHorizontal } from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '../ui/dropdown-menu';
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '../ui/alert-dialog';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../ui/select';
import { Conversation } from '../../types/chat';
import type { Workspace } from '../workspaces/WorkspacesView';

interface ThreadListProps {
  conversations: Conversation[];
  activeId: string | null;
  onDelete: (id: string) => void;
  onRename: (id: string, newTitle: string) => void;
  onTogglePin: (id: string) => void;
  workspaces: Workspace[];
  workspaceId: string;
  onWorkspaceChange: (id: string) => void;
  onManageWorkspaces: () => void;
  workspaceDisabled?: boolean;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export const ThreadList: React.FC<ThreadListProps> = ({
  conversations,
  activeId,
  onDelete,
  onRename,
  onTogglePin,
  workspaces,
  workspaceId,
  onWorkspaceChange,
  onManageWorkspaces,
  workspaceDisabled = false,
  isCollapsed = false,
  onToggleCollapse,
}) => {
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState<string>('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingId]);

  const handleSaveRename = (id: string) => {
    const trimmed = editTitle.trim();
    if (trimmed) {
      onRename(id, trimmed);
    }
    setEditingId(null);
  };

  const handleCancelRename = () => {
    setEditingId(null);
  };

  const pinnedList = conversations.filter((c) => Boolean(c.is_pinned));
  const unpinnedList = conversations.filter((c) => !Boolean(c.is_pinned));

  const renderSessionItem = (conv: Conversation) => {
    const isActive = conv.id === activeId;
    const isEditing = conv.id === editingId;
    const isPinned = Boolean(conv.is_pinned);

    if (isEditing) {
      return (
        <div
          key={conv.id}
          onClick={(e) => e.stopPropagation()}
          className="flex items-center space-x-1 px-2 py-1.5 rounded-xl bg-primary/10 border border-primary/50 shadow-sm"
        >
          <Input
            ref={inputRef}
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleSaveRename(conv.id);
              } else if (e.key === 'Escape') {
                e.preventDefault();
                handleCancelRename();
              }
            }}
            className="flex-1 min-w-0 h-7 text-xs px-2 py-1"
          />
          <Button variant="ghost"
            type="button"
            onClick={() => handleSaveRename(conv.id)}
            title="保存名称"
            className="p-1 text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/10 rounded transition"
          >
            <Check className="w-3.5 h-3.5" />
          </Button>
          <Button variant="ghost"
            type="button"
            onClick={handleCancelRename}
            title="取消"
            className="p-1 text-muted-foreground hover:text-foreground hover:bg-accent rounded transition"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        </div>
      );
    }

    return (
      <ThreadListItemPrimitive.Root
        key={conv.id}
        onDoubleClick={(e) => {
          e.stopPropagation();
          setEditingId(conv.id);
          setEditTitle(conv.title);
        }}
        className={`group flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium cursor-pointer transition ${
          isActive
            ? 'bg-primary/10 text-primary shadow-sm font-semibold'
            : 'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground'
        }`}
      >
        <ThreadListItemPrimitive.Trigger asChild><Button variant="ghost"
          aria-label={conv.title}
          className="h-auto justify-start p-0 hover:bg-transparent flex items-center space-x-2.5 truncate flex-1 min-w-0 mr-1.5 text-xs">
          {isPinned ? (
            <Pin className="w-3.5 h-3.5 shrink-0 text-primary fill-primary/20 rotate-45" />
          ) : (
            <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-70" />
          )}
          <span className="block min-w-0 truncate text-left" title={conv.title}><ThreadListItemPrimitive.Title /></span>
        </Button></ThreadListItemPrimitive.Trigger>

        <div className="flex items-center space-x-0.5 shrink-0">
          {/* 非悬浮时若已置顶，常驻小图钉标志 */}
          {isPinned && (
            <span className="group-hover:hidden p-0.5 text-primary" title="已置顶">
              <Pin className="w-3 h-3 rotate-45 fill-primary/20" />
            </span>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="h-7 w-7" aria-label={`会话操作 ${conv.title}`} onClick={e => e.stopPropagation()}><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={e => e.stopPropagation()}>
              <DropdownMenuItem onSelect={() => onTogglePin(conv.id)}>{isPinned ? <PinOff /> : <Pin />}{isPinned ? '取消置顶' : '置顶会话'}</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => { setEditingId(conv.id); setEditTitle(conv.title); }}><Pencil />重命名会话</DropdownMenuItem>
              <DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" onSelect={() => setPendingDelete(conv)}><Trash2 />删除会话</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </ThreadListItemPrimitive.Root>
    );
  };

  return (
    <>
    <ThreadListPrimitive.Root
      className={`h-full border-r border-sidebar-border bg-sidebar text-sidebar-foreground flex flex-col justify-between select-none transition-all duration-300 ease-in-out shrink-0 overflow-hidden ${
        isCollapsed ? 'w-0 border-r-0 opacity-0 pointer-events-none' : 'w-64 opacity-100'
      }`}
    >
      <div className="w-64 h-full flex flex-col justify-between">
        <div className="p-3.5 space-y-3">
          {/* 顶栏：会话管理标题与折叠按钮 */}
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-bold text-sidebar-foreground">
              会话列表
            </span>
            {onToggleCollapse && (
              <Button variant="ghost"
                onClick={onToggleCollapse}
                title="折叠会话列表"
                className="p-1.5 rounded-lg text-muted-foreground hover:text-sidebar-foreground hover:bg-sidebar-accent transition"
              >
                <PanelLeftClose className="w-4 h-4" />
              </Button>
            )}
          </div>

          <div className="space-y-1.5 px-1">
            <div className="text-[11px] font-medium text-muted-foreground">业务空间</div>
            <Select value={workspaceId || ''} onValueChange={onWorkspaceChange} disabled={workspaceDisabled || workspaces.length === 0}>
              <SelectTrigger aria-label="切换业务空间" className="h-9 bg-background text-xs">
                <SelectValue placeholder={workspaces.length ? '选择业务空间' : '暂无业务空间'} />
              </SelectTrigger>
              <SelectContent>
                {workspaces.map(workspace => (
                  <SelectItem key={workspace.id} value={workspace.id}>{workspace.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {workspaces.length === 0 && (
              <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={onManageWorkspaces}>
                前往创建业务空间
              </Button>
            )}
          </div>

          {/* + New thread 按钮 */}
          <ThreadListPrimitive.New asChild><Button variant="ghost"
            className="w-full flex items-center justify-center space-x-2 px-3 py-2.5 rounded-xl border border-sidebar-border hover:border-primary/80 bg-sidebar hover:bg-sidebar-accent text-sm font-semibold text-sidebar-foreground shadow-sm transition"
          >
            <Plus className="w-4 h-4 text-primary" />
            <span>新建对话</span>
          </Button></ThreadListPrimitive.New>

          {/* 历史会话列表 */}
          <div className="space-y-2 max-h-[calc(100vh-230px)] overflow-y-auto pr-1 custom-scrollbar">
            {conversations.length === 0 ? (
              <div className="text-xs text-muted-foreground text-center py-6">
                暂无历史会话
              </div>
            ) : (
              <>
                {/* 1. 置顶会话分组 */}
                {pinnedList.length > 0 && (
                  <div className="space-y-1">
                    <div className="flex items-center space-x-1 text-[11px] font-semibold text-primary uppercase tracking-wider px-1">
                      <Pin className="w-3 h-3 rotate-45 fill-primary/20" />
                      <span>置顶会话 ({pinnedList.length})</span>
                    </div>
                    <ThreadListPrimitive.Items>{({threadListItem}) => { const conv = pinnedList.find(c => c.id === threadListItem.id); return conv ? renderSessionItem(conv) : null; }}</ThreadListPrimitive.Items>
                  </div>
                )}

                {/* 2. 其它历史会话分组 */}
                <div className="space-y-1">
                  {pinnedList.length > 0 && (
                    <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider px-1 pt-2">
                      历史会话
                    </div>
                  )}
                  <ThreadListPrimitive.Items>{({threadListItem}) => { const conv = unpinnedList.find(c => c.id === threadListItem.id); return conv ? renderSessionItem(conv) : null; }}</ThreadListPrimitive.Items>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="p-3.5 border-t border-sidebar-border text-[11px] text-muted-foreground flex items-center justify-between">
          <span>已隔离租户空间</span>
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
        </div>
      </div>
    </ThreadListPrimitive.Root>
    <AlertDialog open={!!pendingDelete} onOpenChange={open => { if (!open) setPendingDelete(null); }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>删除会话？</AlertDialogTitle><AlertDialogDescription>将删除“{pendingDelete?.title}”及其消息记录。已提交的反馈及问答快照将保留供核查。</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel><AlertDialogAction onClick={() => { if (pendingDelete) onDelete(pendingDelete.id); setPendingDelete(null); }}>确认删除</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
};
