
import React from "react";
import { Link, useLocation } from "react-router-dom";
import { createPageUrl } from "@/utils";
import { useAuth } from "@/contexts/AuthContext";
import {
  Settings,
  TrendingUp,
  Package,
  BarChart3,
  DollarSign,
  Users,
  LogOut,
  MessageSquare,
  Truck,
  ClipboardList
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
  SidebarFooter,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const navigationSections = [
  {
    label: "Analytics",
    items: [
      { title: "Reports", url: createPageUrl("Reports"), icon: BarChart3 },
    ]
  },
  {
    label: "Operations",
    items: [
      { title: "Pricing", url: createPageUrl("Pricing"), icon: DollarSign },
      { title: "Korealy Tracking", url: createPageUrl("KorealyProcessor"), icon: Package },
    ]
  },
  {
    label: "Sales & Support",
    items: [
      { title: "Support Inbox", url: createPageUrl("Support"), icon: MessageSquare },
      { title: "Tracking", url: createPageUrl("Tracking"), icon: Truck },
      { title: "Activity Center", url: createPageUrl("Activity"), icon: ClipboardList },
    ]
  },
  {
    label: "Settings",
    items: [
      { title: "Integrations", url: createPageUrl("Settings"), icon: Settings },
    ]
  }
];

export default function Layout({ children }) {
  const location = useLocation();
  const { user, isAdmin, logout } = useAuth();

  return (
    <SidebarProvider>
      <div className="min-h-screen flex w-full bg-gradient-to-br from-slate-50 to-slate-100">
        <Sidebar className="border-r border-slate-200 bg-white">
          <SidebarHeader className="border-b border-slate-200 p-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg">
                <TrendingUp className="w-6 h-6 text-white" />
              </div>
              <div>
                <h2 className="font-bold text-slate-900 text-lg">Mirai Skin</h2>
                <p className="text-xs text-slate-500">Admin Dashboard</p>
              </div>
            </div>
          </SidebarHeader>

          <SidebarContent className="p-3">
            {navigationSections.map((section) => (
              <SidebarGroup key={section.label} className="mb-4">
                <SidebarGroupLabel className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 py-2">
                  {section.label}
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {section.items.map((item) => (
                      <SidebarMenuItem key={item.title}>
                        <SidebarMenuButton
                          asChild
                          className={`hover:bg-indigo-50 hover:text-indigo-700 transition-all duration-200 rounded-lg mb-1 ${
                            location.pathname === item.url ? 'bg-indigo-100 text-indigo-700 font-medium' : ''
                          }`}
                        >
                          <Link to={item.url} className="flex items-center gap-3 px-3 py-2.5">
                            <item.icon className="w-4 h-4" />
                            <span>{item.title}</span>
                            {item.badge && (
                              <Badge variant="secondary" className="ml-auto text-xs bg-amber-100 text-amber-700 border-0">
                                {item.badge}
                              </Badge>
                            )}
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}

            {/* Admin section */}
            {isAdmin && (
              <SidebarGroup className="mb-4">
                <SidebarGroupLabel className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-3 py-2">
                  Admin
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        asChild
                        className={`hover:bg-indigo-50 hover:text-indigo-700 transition-all duration-200 rounded-lg mb-1 ${
                          location.pathname === '/UserManagement' ? 'bg-indigo-100 text-indigo-700 font-medium' : ''
                        }`}
                      >
                        <Link to="/UserManagement" className="flex items-center gap-3 px-3 py-2.5">
                          <Users className="w-4 h-4" />
                          <span>User Management</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            )}
          </SidebarContent>

          <SidebarFooter className="border-t border-slate-200 p-4">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="w-full justify-start p-0 h-auto hover:bg-transparent">
                  <div className="flex items-center gap-3 w-full">
                    <Avatar className="h-9 w-9">
                      {user?.picture && <AvatarImage src={user.picture} alt={user.name} />}
                      <AvatarFallback className="bg-gradient-to-br from-indigo-500 to-purple-600 text-white font-semibold">
                        {user?.name?.charAt(0)?.toUpperCase() || user?.email?.charAt(0)?.toUpperCase() || 'U'}
                      </AvatarFallback>
                    </Avatar>
                    <div className="flex-1 min-w-0 text-left">
                      <p className="font-medium text-slate-900 text-sm truncate">
                        {user?.name || 'User'}
                      </p>
                      <p className="text-xs text-slate-500 truncate">{user?.email || ''}</p>
                    </div>
                  </div>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>My Account</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {isAdmin && (
                  <DropdownMenuItem asChild>
                    <Link to="/UserManagement" className="flex items-center">
                      <Users className="mr-2 h-4 w-4" />
                      User Management
                    </Link>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={logout} className="text-red-600">
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign Out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarFooter>
        </Sidebar>

        <main className="flex-1 flex flex-col overflow-hidden">
          <header className="bg-white border-b border-slate-200 px-6 py-4 lg:hidden">
            <div className="flex items-center gap-4">
              <SidebarTrigger className="hover:bg-slate-100 p-2 rounded-lg transition-colors duration-200" />
              <h1 className="text-xl font-bold text-slate-900">Mirai Skin Admin</h1>
            </div>
          </header>

          <div className="flex-1 overflow-auto">
            {children}
          </div>
        </main>
      </div>
    </SidebarProvider>
  );
}
