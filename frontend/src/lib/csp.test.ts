import { describe, expect, it } from "vitest";

import { ARTWORK_HOSTS, contentSecurityPolicy, newNonce } from "./csp";

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name, values];
    }),
  );
}

describe("contentSecurityPolicy", () => {
  it("only runs scripts carrying this request's nonce in production", () => {
    const policy = directives(contentSecurityPolicy("abc123=="));
    expect(policy.get("script-src")).toEqual(["'self'", "'nonce-abc123=='", "'strict-dynamic'"]);
    expect(policy.get("script-src")).not.toContain("'unsafe-inline'");
    expect(policy.get("script-src")).not.toContain("'unsafe-eval'");
    expect(policy.get("object-src")).toEqual(["'none'"]);
    expect(policy.get("base-uri")).toEqual(["'none'"]);
    expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    expect(policy.get("connect-src")).toEqual(["'self'"]);
    expect(policy.get("worker-src")).toEqual(["'self'"]);
  });

  it("allows artwork only from the providers' CDNs, over https", () => {
    const images = directives(contentSecurityPolicy("n")).get("img-src") ?? [];
    for (const host of ARTWORK_HOSTS) {
      expect(images).toContain(`https://${host}`);
      expect(images).toContain(`https://*.${host}`);
    }
    expect(images.filter((source) => source.startsWith("http:"))).toEqual([]);
    expect(images).not.toContain("*");
    expect(images).not.toContain("https:");
  });

  it("relaxes only what Next.js dev tooling needs in development", () => {
    const policy = directives(contentSecurityPolicy("n", { dev: true }));
    expect(policy.get("script-src")).toContain("'unsafe-eval'");
    expect(policy.get("connect-src")).toEqual(["'self'", "ws:", "wss:"]);
  });
});

describe("newNonce", () => {
  it("is 128 random bits in base64, different every time", () => {
    const nonces = new Set(Array.from({ length: 50 }, () => newNonce()));
    expect(nonces.size).toBe(50);
    for (const nonce of nonces) expect(nonce).toMatch(/^[A-Za-z0-9+/]{22}==$/);
  });
});
