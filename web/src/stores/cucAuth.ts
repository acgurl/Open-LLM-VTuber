import { create } from 'zustand';
import type { CucAuthService } from '../utils/cucAuthPrompt';

interface CucAuthState {
  available: boolean | null;
  activeCardId: string | null;
  confirmedAt: Record<CucAuthService, number>;
  setAvailable: (available: boolean) => void;
  claimActiveCard: (id: string) => void;
  releaseActiveCard: (id: string) => void;
  notifyConfirmed: (service: CucAuthService) => void;
}

export const useCucAuth = create<CucAuthState>((set) => ({
  available: null,
  activeCardId: null,
  confirmedAt: {
    sso: 0,
    mail: 0,
    net: 0,
    opac: 0,
  },

  setAvailable: (available) =>
    set((s) => (s.available === available ? s : { available })),

  claimActiveCard: (id) =>
    set((s) => (s.activeCardId === id ? s : { activeCardId: id })),

  releaseActiveCard: (id) =>
    set((s) => (s.activeCardId === id ? { activeCardId: null } : s)),

  notifyConfirmed: (service) =>
    set((s) => ({
      available: true,
      confirmedAt: { ...s.confirmedAt, [service]: Date.now() },
    })),
}));
