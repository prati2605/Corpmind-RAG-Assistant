import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { refreshSession, setAccessToken, setOnAuthLost } from "../api/client";
import { auth, me } from "../api/endpoints";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | signed-in | signed-out
  const qc = useQueryClient();

  const signOutLocally = useCallback(() => {
    setAccessToken(null);
    setUser(null);
    setStatus("signed-out");
    qc.clear();
  }, [qc]);

  useEffect(() => {
    setOnAuthLost(signOutLocally);
    // On page load, try to resume the session from the httpOnly refresh cookie.
    refreshSession()
      .then(() => me.get())
      .then((u) => {
        setUser(u);
        setStatus("signed-in");
      })
      .catch(() => setStatus("signed-out"));
  }, [signOutLocally]);

  const login = useCallback(async (email, password) => {
    const tokens = await auth.login(email, password);
    setAccessToken(tokens.access_token);
    const u = await me.get();
    setUser(u);
    setStatus("signed-in");
    return u;
  }, []);

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      signOutLocally();
    }
  }, [signOutLocally]);

  const reloadUser = useCallback(async () => setUser(await me.get()), []);

  const value = useMemo(
    () => ({
      user,
      status,
      login,
      logout,
      reloadUser,
      isAdmin: user?.role === "admin",
      canManageDocuments: user?.role === "admin" || user?.role === "hr",
    }),
    [user, status, login, logout, reloadUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
