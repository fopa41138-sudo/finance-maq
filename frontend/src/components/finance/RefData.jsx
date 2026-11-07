import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const RefCtx = createContext(null);

export const RefDataProvider = ({ children }) => {
  const { isAdmin } = useAuth();
  const [categories, setCategories] = useState([]);
  const [techs, setTechs] = useState([]);
  const [orders, setOrders] = useState([]);

  const reload = useCallback(async () => {
    const [c, o] = await Promise.all([api.get("/finance/categories"), api.get("/os")]);
    setCategories(c.data);
    setOrders(o.data);
    if (isAdmin) {
      const u = await api.get("/users");
      setTechs(u.data.filter((x) => x.role === "tecnico"));
    }
  }, [isAdmin]);

  useEffect(() => {
    reload();
  }, [reload]);

  const catById = Object.fromEntries(categories.map((c) => [c.id, c]));
  const osById = Object.fromEntries(orders.map((o) => [o.id, o]));
  const techById = Object.fromEntries(techs.map((t) => [t.id, t]));

  return (
    <RefCtx.Provider value={{ categories, techs, orders, catById, osById, techById, reload }}>
      {children}
    </RefCtx.Provider>
  );
};

export const useRef_ = () => useContext(RefCtx);
