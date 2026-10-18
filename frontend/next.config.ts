import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: '/login',
        destination: '/auth',
        permanent: true,
      },
      {
        source: '/register',
        destination: '/auth?mode=register',
        permanent: true,
      },
      {
        source: '/signin',
        destination: '/auth',
        permanent: true,
      },
      {
        source: '/signup',
        destination: '/auth?mode=register',
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
