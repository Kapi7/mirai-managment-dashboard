
import React, { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { createPageUrl } from "@/utils";
import { useAuth } from "@/contexts/AuthContext";
import {
  Settings,
  Package,
  BarChart3,
  DollarSign,
  Users,
  LogOut,
  MessageSquare,
  Truck,
  ClipboardList,
  Target,
  FileText,
  Share2,
  LayoutGrid,
  X,
} from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { watchTables } from "@/lib/cardifyTables";
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
    ],
  },
  {
    label: "Marketing",
    items: [
      { title: "Meta Ads", url: createPageUrl("Marketing"), icon: Target },
      { title: "Blog Creator", url: createPageUrl("BlogCreator"), icon: FileText },
      { title: "Social Media", url: createPageUrl("SocialMedia"), icon: Share2 },
    ],
  },
  {
    label: "Operations",
    items: [
      { title: "Pricing", url: createPageUrl("Pricing"), icon: DollarSign },
      { title: "Korealy Tracking", url: createPageUrl("KorealyProcessor"), icon: Package },
    ],
  },
  {
    label: "Sales & Support",
    items: [
      { title: "Support Inbox", url: createPageUrl("Support"), icon: MessageSquare },
      { title: "Tracking", url: createPageUrl("Tracking"), icon: Truck },
      { title: "Activity Center", url: createPageUrl("Activity"), icon: ClipboardList },
    ],
  },
  {
    label: "Settings",
    items: [
      { title: "Integrations", url: createPageUrl("Settings"), icon: Settings },
    ],
  },
];

// Bottom thumb-nav on mobile: the 4 most-used destinations + "More" sheet
const mobilePrimary = [
  { title: "Reports", url: createPageUrl("Reports"), icon: BarChart3 },
  { title: "Pricing", url: createPageUrl("Pricing"), icon: DollarSign },
  { title: "Support", url: createPageUrl("Support"), icon: MessageSquare },
  { title: "Tracking", url: createPageUrl("Tracking"), icon: Truck },
];

export default function Layout({ children }) {
  const location = useLocation();
  const { user, isAdmin, logout } = useAuth();
  const [moreOpen, setMoreOpen] = useState(false);

  // Close the mobile sheet on navigation
  useEffect(() => { setMoreOpen(false); }, [location.pathname]);

  // Legacy pages: keep wide tables stamped for the mobile card treatment
  useEffect(() => watchTables(document.body), []);

  // "/" serves Reports — count it as active. Route paths are capitalized
  // (/Reports) while createPageUrl lowercases, so compare case-insensitively.
  const isActive = (url) =>
    location.pathname.toLowerCase() === url.toLowerCase() ||
    (url === createPageUrl("Reports") && location.pathname === "/");

  const currentTitle = (() => {
    for (const s of navigationSections) {
      const hit = s.items.find((i) => isActive(i.url));
      if (hit) return hit.title;
    }
    if (location.pathname === "/UserManagement") return "User Management";
    return "Mirai Skin";
  })();

  const navLink = (item, onNavigate) => {
    const active = isActive(item.url);
    return (
      <Link
        key={item.title}
        to={item.url}
        onClick={onNavigate}
        className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl mb-0.5 text-[0.86rem] font-medium transition-all duration-150 border ${
          active
            ? "bg-gradient-to-r from-rose-500/15 to-fuchsia-500/10 border-rose-400/25 text-white shadow-[0_0_18px_-6px_rgba(251,113,133,0.45)]"
            : "border-transparent text-[#a9b7cc] hover:text-white hover:bg-white/[0.04]"
        }`}
      >
        <item.icon
          className={`w-4 h-4 shrink-0 transition-colors ${active ? "text-rose-300" : "text-[#7487a3] group-hover:text-rose-200"}`}
        />
        <span className="truncate">{item.title}</span>
      </Link>
    );
  };

  const brand = (
    <div className="flex flex-col gap-1 min-w-0">
      <img
        src="/mirai-logo-white.png"
        alt="Mirai Skin"
        className="h-[16px] w-auto max-w-[140px] object-contain object-left"
      />
      <p className="text-[0.58rem] font-bold tracking-[0.3em] uppercase bg-gradient-to-r from-rose-300 to-violet-300 bg-clip-text text-transparent">
        Management
      </p>
    </div>
  );

  const userFooter = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="w-full flex items-center gap-3 p-2 rounded-xl hover:bg-white/[0.05] transition-colors text-left">
          <Avatar className="h-9 w-9 border border-[#2b3a55]">
            {user?.picture && <AvatarImage src={user.picture} alt={user.name} />}
            <AvatarFallback className="bg-gradient-to-br from-rose-500 to-violet-500 text-white font-semibold">
              {user?.name?.charAt(0)?.toUpperCase() || user?.email?.charAt(0)?.toUpperCase() || "U"}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-white text-sm truncate">{user?.name || "User"}</p>
            <p className="text-xs text-[#8fa0b8] truncate">{user?.email || ""}</p>
          </div>
        </button>
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
        <DropdownMenuItem onClick={logout} className="text-red-500">
          <LogOut className="mr-2 h-4 w-4" />
          Sign Out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <div className="min-h-screen w-full flex">
      {/* ── Desktop sidebar (≥ lg) ─────────────────────────────────────── */}
      <aside className="desk-only w-[248px] shrink-0 sticky top-0 h-screen flex flex-col border-r border-[#22304d] bg-[#0d1426]/90 backdrop-blur">
        <div className="p-5 pb-4 border-b border-[#22304d]">{brand}</div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {navigationSections.map((section) => (
            <div key={section.label} className="mb-4">
              <div className="text-[0.62rem] font-bold uppercase tracking-[0.16em] text-[#5c6e8c] px-3 pb-1.5">
                {section.label}
              </div>
              {section.items.map((item) => navLink(item))}
            </div>
          ))}

          {isAdmin && (
            <div className="mb-4">
              <div className="text-[0.62rem] font-bold uppercase tracking-[0.16em] text-[#5c6e8c] px-3 pb-1.5">
                Admin
              </div>
              {navLink({ title: "User Management", url: "/UserManagement", icon: Users })}
            </div>
          )}
        </nav>

        <div className="border-t border-[#22304d] p-3">{userFooter}</div>
      </aside>

      {/* ── Main column ────────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* Mobile top bar (< lg) */}
        <header className="mob-only sticky top-0 z-40 flex items-center justify-between gap-3 px-4 py-2.5 bg-[#0d1426]/92 backdrop-blur border-b border-[#22304d]">
          {brand}
          <span className="text-[0.78rem] font-bold text-[#a9b7cc] truncate">{currentTitle}</span>
        </header>

        <div className="flex-1 min-w-0">{children}</div>
      </main>

      {/* ── Mobile floating thumb-nav (< lg) ───────────────────────────── */}
      <nav className="mob-only fixed bottom-[max(14px,env(safe-area-inset-bottom))] inset-x-3 z-50 rounded-2xl border border-[#2e3d5c] bg-[#0f1830]/92 backdrop-blur-xl shadow-[0_14px_44px_-10px_rgba(0,0,0,0.85),0_0_0_1px_rgba(99,102,241,0.06)] overflow-hidden">
        <div className="m-thumbgrid">
          {mobilePrimary.map((item) => {
            const active = isActive(item.url);
            return (
              <Link
                key={item.title}
                to={item.url}
                className={`relative flex flex-col items-center gap-0.5 py-2 text-[0.6rem] font-bold transition-colors ${
                  active ? "text-rose-300" : "text-[#7487a3]"
                }`}
              >
                {active && (
                  <span className="absolute top-0 h-[2.5px] w-9 rounded-full bg-gradient-to-r from-rose-400 to-fuchsia-400 shadow-[0_0_10px_rgba(251,113,133,0.7)]" />
                )}
                <item.icon className="w-5 h-5" />
                {item.title}
              </Link>
            );
          })}
          <button
            onClick={() => setMoreOpen(true)}
            className={`flex flex-col items-center gap-0.5 py-2 text-[0.6rem] font-bold transition-colors ${
              moreOpen ? "text-rose-300" : "text-[#7487a3]"
            }`}
          >
            <LayoutGrid className="w-5 h-5" />
            More
          </button>
        </div>
      </nav>

      {/* ── Mobile "More" sheet ────────────────────────────────────────── */}
      {moreOpen && (
        <div className="mob-only fixed inset-0 z-[60]" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setMoreOpen(false)} />
          <div className="absolute bottom-0 inset-x-0 max-h-[82vh] overflow-y-auto rounded-t-2xl border-t border-[#2b3a55] bg-[#101a30] p-4 pb-[calc(16px+env(safe-area-inset-bottom))] shadow-[0_-18px_50px_-12px_rgba(0,0,0,0.8)]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-extrabold text-white">All sections</span>
              <button
                onClick={() => setMoreOpen(false)}
                className="p-2 rounded-lg bg-white/[0.06] text-[#a9b7cc] hover:text-white"
                aria-label="Close menu"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {navigationSections.map((section) => (
              <div key={section.label} className="mb-3">
                <div className="text-[0.62rem] font-bold uppercase tracking-[0.16em] text-[#5c6e8c] px-1 pb-1.5">
                  {section.label}
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {section.items.map((item) => navLink(item, () => setMoreOpen(false)))}
                </div>
              </div>
            ))}
            {isAdmin && (
              <div className="mb-1">
                <div className="text-[0.62rem] font-bold uppercase tracking-[0.16em] text-[#5c6e8c] px-1 pb-1.5">
                  Admin
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {navLink({ title: "User Management", url: "/UserManagement", icon: Users }, () => setMoreOpen(false))}
                </div>
              </div>
            )}
            <div className="border-t border-[#22304d] mt-3 pt-3">{userFooter}</div>
          </div>
        </div>
      )}
    </div>
  );
}
