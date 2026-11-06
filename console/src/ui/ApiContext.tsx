import { createContext, useContext, type ReactNode } from "react";
import { createApi, token, type Api } from "../lib/api";

const defaultApi = createApi({ getToken: token.get });
const Ctx = createContext<Api>(defaultApi);

/** Tests inject a fake Api; the app uses the real one. */
export function ApiProvider({ api, children }: { api?: Api; children: ReactNode }) {
  return <Ctx.Provider value={api ?? defaultApi}>{children}</Ctx.Provider>;
}

export const useApi = (): Api => useContext(Ctx);
