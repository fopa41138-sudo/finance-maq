import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

const AuthCtx = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem("fin_token")) {
      setReady(true);
      return;
    }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => localStorage.removeItem("fin_token"))
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (userId) => {
    const r = await api.post("/auth/demo-login", { user_id: userId });
    localStorage.setItem("fin_token", r.data.token);
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("fin_token");
    setUser(null);
  }, []);

  const isAdmin = user?.role === "admin";
  const hasFinance = isAdmin || user?.finance_access === "own";

  return <AuthCtx.Provider value={{ user, ready, login, logout, isAdmin, hasFinance }}>{children}</AuthCtx.Provider>;
};

export const useAuth = () => useContext(AuthCtx);
