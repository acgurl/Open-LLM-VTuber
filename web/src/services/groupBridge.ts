import { useGroup } from '../stores/group';

const CHANNEL = 'ollmvt-group';
const PEER_TTL_MS = 10_000;
const ANNOUNCE_INTERVAL_MS = 3_000;

// BroadcastChannel：同浏览器同账号的标签页互相发现 client_uid，供群聊邀请。
class GroupBridge {
  private bc: BroadcastChannel | null = null;
  private myUid: string | null = null;
  private peers = new Map<string, number>();

  setUid(uid: string) {
    this.myUid = uid;
    this.init();
    this.announce();
  }

  private init() {
    if (this.bc || typeof BroadcastChannel === 'undefined') return;
    this.bc = new BroadcastChannel(CHANNEL);
    this.bc.onmessage = (ev: MessageEvent) => {
      const d = ev.data as { kind?: string; uid?: string } | null;
      if (!d?.uid || d.uid === this.myUid) return;
      if (d.kind === 'announce') {
        this.peers.set(d.uid, Date.now());
        this.publish();
      } else if (d.kind === 'who') {
        this.announce();
      }
    };
    this.bc.postMessage({ kind: 'who', uid: 'bootstrap' });
    window.setInterval(() => {
      this.announce();
      this.prune();
    }, ANNOUNCE_INTERVAL_MS);
  }

  private announce() {
    if (this.bc && this.myUid) {
      this.bc.postMessage({ kind: 'announce', uid: this.myUid });
    }
  }

  private prune() {
    const now = Date.now();
    let changed = false;
    for (const [uid, seen] of this.peers) {
      if (now - seen > PEER_TTL_MS) {
        this.peers.delete(uid);
        changed = true;
      }
    }
    if (changed) this.publish();
  }

  private publish() {
    useGroup
      .getState()
      .setPeers([...this.peers.entries()].map(([uid, seen]) => ({ uid, seen })));
  }
}

export const groupBridge = new GroupBridge();
