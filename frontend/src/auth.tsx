import { createContext, useContext, ReactNode } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api, ApiError } from "./api";

interface AuthState {
  username: string | null;
  isAdmin: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: (_count, err) => !(err instanceof ApiError && err.status === 401),
    staleTime: 60_000,
  });

  const loginMutation = useMutation({
    mutationFn: ({ u, p }: { u: string; p: string }) => api.login(u, p),
    onSuccess: (data) => qc.setQueryData(["me"], data),
  });

  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.setQueryData(["me"], null);
      qc.clear();
    },
  });

  const value: AuthState = {
    username: meQuery.data?.username ?? null,
    isAdmin: Boolean(meQuery.data?.is_admin),
    loading: meQuery.isLoading,
    login: async (u, p) => {
      await loginMutation.mutateAsync({ u, p });
    },
    logout: async () => {
      await logoutMutation.mutateAsync();
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
