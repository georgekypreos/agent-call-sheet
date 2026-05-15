/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow API routes to use the Prisma + libSQL combo
  experimental: {
    serverComponentsExternalPackages: ["@prisma/client", "@libsql/client", "@prisma/adapter-libsql"],
  },
};

export default nextConfig;
