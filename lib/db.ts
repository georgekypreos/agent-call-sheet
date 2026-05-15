import { PrismaClient } from "@prisma/client";
import { PrismaLibSQL } from "@prisma/adapter-libsql";
import { createClient } from "@libsql/client";

/**
 * Single Prisma client instance. In dev we attach it to globalThis so hot reload
 * doesn't spawn a new connection on every save.
 *
 * Local development: set DATABASE_URL=file:./dev.db in .env.local (regular SQLite file).
 * Production (Vercel + Turso): set DATABASE_URL=libsql://<your-db>.turso.io and
 * TURSO_AUTH_TOKEN=<token> — the libSQL adapter takes over.
 */
function buildClient(): PrismaClient {
  const url = process.env.DATABASE_URL || "file:./dev.db";
  const isTurso = url.startsWith("libsql://") || url.startsWith("http://") || url.startsWith("https://");

  if (isTurso) {
    const libsql = createClient({
      url,
      authToken: process.env.TURSO_AUTH_TOKEN,
    });
    const adapter = new PrismaLibSQL(libsql);
    return new PrismaClient({ adapter });
  }
  // Local file-backed SQLite — Prisma's default sqlite driver is fine here.
  return new PrismaClient();
}

declare global {
  // eslint-disable-next-line no-var
  var __prisma: PrismaClient | undefined;
}

export const db: PrismaClient = global.__prisma ?? buildClient();

if (process.env.NODE_ENV !== "production") {
  global.__prisma = db;
}
