import React from 'react';
import { SidebarTrigger } from '../ui/sidebar';
import { Avatar, AvatarFallback } from '../ui/avatar';
import { Breadcrumb, BreadcrumbList, BreadcrumbItem, BreadcrumbPage, BreadcrumbSeparator } from '../ui/breadcrumb';
import { Button } from '../ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '../ui/tooltip';
import { Sun, Moon, LogOut } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { useAuth } from '../../context/AuthContext';

interface HeaderProps {
  currentTab: string;
}

export const Header: React.FC<HeaderProps> = ({
  currentTab,
}) => {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  const getBreadcrumbs = () => {
    switch (currentTab) {
      case 'chat':
        return '智能问数 / 对话工作区';
      case 'workspaces':
        return '业务空间 / 空间管理';
      case 'feedback':
        return '反馈管理 / 回复校对';
      case 'config':
        return '系统管理 / 应用配置';
      case 'knowledge':
        return '数据管理 / 知识库';
      case 'data':
        return '数据管理 / 业务数据';
      default:
        return '商析 BusinessLens';
    }
  };

  return (
    <header className="h-14 border-b border-border bg-card text-card-foreground px-6 flex items-center justify-between transition-colors">
      <div className="flex items-center space-x-1 text-sm text-muted-foreground font-medium">
        <SidebarTrigger aria-label="展开或折叠菜单栏" className="-ml-2 mr-2" />
        <Breadcrumb><BreadcrumbList>{getBreadcrumbs().split(' / ').map((label,index,all) => <React.Fragment key={label}>{index > 0 && <BreadcrumbSeparator />}<BreadcrumbItem>{index === all.length - 1 ? <BreadcrumbPage>{label}</BreadcrumbPage> : <span>{label}</span>}</BreadcrumbItem></React.Fragment>)}</BreadcrumbList></Breadcrumb>
      </div>

      <div className="flex items-center space-x-4">
        {/* 暗黑/明亮主题切换 */}
        <Tooltip><TooltipTrigger asChild>
        <Button variant="ghost" size="icon"
          onClick={toggleTheme}
          title={theme === 'dark' ? '切换为明亮模式' : '切换为暗黑模式'}
          className="p-2 rounded-lg text-muted-foreground hover:text-foreground transition"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
        </Button>
        </TooltipTrigger><TooltipContent>{theme === 'dark' ? '切换为明亮模式' : '切换为暗黑模式'}</TooltipContent></Tooltip>

        {/* 用户信息与登出 */}
        {user && (
          <div className="flex items-center space-x-3 pl-3 border-l border-border">
            <div className="flex items-center space-x-2">
              <Avatar className="h-7 w-7"><AvatarFallback className="bg-primary/10 text-primary text-xs font-bold">{user.username.slice(0, 2).toUpperCase()}</AvatarFallback></Avatar>
              <span className="text-sm font-medium text-foreground">
                {user.username}
              </span>
            </div>

            <Button variant="ghost" size="icon"
              onClick={logout}
              title="退出登录"
              className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition"
            >
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        )}
      </div>
    </header>
  );
};
