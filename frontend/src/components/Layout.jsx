import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { FileText, History, LayoutDashboard, LogOut, Menu, MessagesSquare, Settings, ShieldCheck, X } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { ROLE_LABEL, cx } from "./ui";

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-4 py-5">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="6" fill="#F6F7F4" />
        <path d="M9 8h11l3 3v13H9z" fill="#1B2A3A" />
        <rect x="12" y="15" width="8" height="3" fill="#F3DA63" />
      </svg>
      <span className="text-lg font-semibold tracking-tight text-paper">CorpMind</span>
    </div>
  );
}

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const nav = [
    { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/chat", label: "Ask", icon: MessagesSquare },
    { to: "/history", label: "Chat history", icon: History },
    { to: "/documents", label: "Documents", icon: FileText },
    { to: "/settings", label: "Profile & settings", icon: Settings },
    ...(isAdmin ? [{ to: "/admin", label: "Admin", icon: ShieldCheck }] : []),
  ];
  const fullBleed = location.pathname.startsWith("/chat");

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col bg-ink text-paper/85">
      <Brand />
      <ul className="flex-1 space-y-0.5 px-2">
        {nav.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cx(
                  "flex items-center gap-3 rounded-[4px] px-3 py-2 text-[0.95rem]",
                  isActive ? "bg-paper/12 font-medium text-paper shadow-[inset_3px_0_0_#F3DA63]" : "hover:bg-paper/8 hover:text-paper",
                )
              }
            >
              <Icon size={18} strokeWidth={1.75} />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-paper/15 p-3">
        <div className="px-1 pb-2">
          <p className="truncate text-sm font-medium text-paper">{user?.full_name}</p>
          <p className="truncate text-xs text-paper/60">{user?.email}</p>
          <p className="mt-1 text-xs text-paper/60">Signed in as {ROLE_LABEL[user?.role]}</p>
        </div>
        <button onClick={logout} className="flex w-full items-center gap-2 rounded-[4px] px-2 py-1.5 text-sm hover:bg-paper/8 hover:text-paper">
          <LogOut size={16} /> Sign out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-sheet focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="hidden w-60 shrink-0 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setOpen(false)} />
          <aside className="relative h-full w-64">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-rule bg-sheet px-3 py-2 lg:hidden">
          <button aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)} className="rounded p-1.5 hover:bg-paper">
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
          <span className="font-semibold">CorpMind</span>
        </div>
        <main id="main" className={cx("min-h-0 flex-1", fullBleed ? "overflow-hidden" : "overflow-y-auto px-5 py-6 sm:px-8 lg:px-10")}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
