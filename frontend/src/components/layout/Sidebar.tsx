import { useAuth } from '../../context/AuthContext';
import React, { useState, useEffect } from 'react';
import { MessageSquare, Settings, Sliders, Database, Table2, Layers, Flag, ChevronRight, Bot, CheckSquare } from 'lucide-react';
import { Sidebar as SidebarRoot, SidebarContent, SidebarFooter, SidebarHeader, SidebarGroup, SidebarMenu, SidebarMenuItem, SidebarMenuButton, SidebarMenuSub, SidebarMenuSubItem, SidebarMenuSubButton, SidebarTrigger, useSidebar } from '../ui/sidebar';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../ui/collapsible';

// Keep selected pages visually distinct from hover and expanded groups in both themes.
const activeMenuClass = "data-[active=true]:bg-primary/10 data-[active=true]:text-primary data-[active=true]:font-semibold data-[active=true]:hover:bg-primary/20 data-[active=true]:hover:text-primary data-[active=true]:[&>svg]:text-primary";

interface SidebarProps { currentTab: string; onTabChange: (tab: string) => void; }

export const Sidebar: React.FC<SidebarProps> = ({currentTab, onTabChange}) => {
  const { user } = useAuth();
  const [dataOpen, setDataOpen] = useState(true);
  const [systemOpen, setSystemOpen] = useState(true);
  const [feedbackOpen, setFeedbackOpen] = useState(true);
  const { setOpenMobile } = useSidebar();
  useEffect(() => {
    if (currentTab === 'data' || currentTab === 'workspaces') setDataOpen(true);
    if (currentTab === 'config') setSystemOpen(true);
    if (currentTab === 'feedback') setFeedbackOpen(true);
  }, [currentTab]);
  const navigate = (tab: string) => { onTabChange(tab); setOpenMobile(false); };
  return <SidebarRoot collapsible="offcanvas" className="border-r">
    <SidebarHeader className="flex-row items-center justify-between p-4">
      <span className="flex items-center gap-2.5 font-bold"><Bot className="h-8 w-8 rounded-lg bg-primary p-1.5 text-primary-foreground" />经管之星 BusinessLens</span>
      <SidebarTrigger aria-label="折叠菜单栏" />
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup><SidebarMenu>
        <SidebarMenuItem><SidebarMenuButton className={activeMenuClass} isActive={currentTab === 'chat'} onClick={() => navigate('chat')} aria-current={currentTab === 'chat' ? 'page' : undefined}><MessageSquare /><span>智能问数</span></SidebarMenuButton></SidebarMenuItem>
        <Collapsible asChild open={dataOpen} onOpenChange={setDataOpen}>
          <SidebarMenuItem>
            <CollapsibleTrigger asChild><SidebarMenuButton className="group" aria-label="数据管理"><Database /><span>数据管理</span><ChevronRight className="ml-auto transition-transform group-data-[state=open]:rotate-90" /></SidebarMenuButton></CollapsibleTrigger>
            <CollapsibleContent><SidebarMenuSub>
              {[
                {id:'workspaces',label:'业务空间',Icon:Layers},
                {id:'data',label:'业务数据',Icon:Table2},
              ].map(({id,label,Icon}) => <SidebarMenuSubItem key={id}>
                <SidebarMenuSubButton asChild className={`w-full ${activeMenuClass}`} isActive={currentTab === id}><button type="button" onClick={() => navigate(id)} aria-current={currentTab === id ? 'page' : undefined}><Icon /><span>{label}</span></button></SidebarMenuSubButton>
              </SidebarMenuSubItem>)}
            </SidebarMenuSub></CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>
        <Collapsible asChild open={systemOpen} onOpenChange={setSystemOpen}>
          <SidebarMenuItem>
            <CollapsibleTrigger asChild><SidebarMenuButton className="group"><Settings /><span>系统管理</span><ChevronRight className="ml-auto transition-transform group-data-[state=open]:rotate-90" /></SidebarMenuButton></CollapsibleTrigger>
            <CollapsibleContent><SidebarMenuSub><SidebarMenuSubItem><SidebarMenuSubButton asChild className={`w-full ${activeMenuClass}`} isActive={currentTab === 'config'}><button type="button" onClick={() => navigate('config')} aria-current={currentTab === 'config' ? 'page' : undefined}><Sliders /><span>应用配置</span></button></SidebarMenuSubButton></SidebarMenuSubItem></SidebarMenuSub></CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>
        {user && <Collapsible asChild open={feedbackOpen} onOpenChange={setFeedbackOpen}>
          <SidebarMenuItem>
            <CollapsibleTrigger asChild><SidebarMenuButton className="group" aria-label="反馈管理"><Flag /><span>反馈管理</span><ChevronRight className="ml-auto transition-transform group-data-[state=open]:rotate-90" /></SidebarMenuButton></CollapsibleTrigger>
            <CollapsibleContent><SidebarMenuSub><SidebarMenuSubItem><SidebarMenuSubButton asChild className={`w-full ${activeMenuClass}`} isActive={currentTab === 'feedback'}><button type="button" onClick={() => navigate('feedback')} aria-current={currentTab === 'feedback' ? 'page' : undefined}><CheckSquare /><span>回复校对</span></button></SidebarMenuSubButton></SidebarMenuSubItem></SidebarMenuSub></CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>}
      </SidebarMenu></SidebarGroup>
    </SidebarContent>
    <SidebarFooter className="border-t p-4 text-xs text-muted-foreground">AI 业务数据检索与分析 v1.0</SidebarFooter>
  </SidebarRoot>;
};
