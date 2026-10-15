"use client";

import { createContext, useContext } from "react";

import type { User } from "@/types/api";

const UserContext = createContext<User | null>(null);

export function UserProvider({ children, user }: { children: React.ReactNode; user: User }) {
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function useCurrentUser() {
  const user = useContext(UserContext);
  if (!user) throw new Error("useCurrentUser must be used inside UserProvider");
  return user;
}
