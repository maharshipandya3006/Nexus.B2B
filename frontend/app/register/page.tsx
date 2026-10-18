'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function RegisterPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/auth?mode=register');
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#dceeff] text-black">
      <div className="text-center font-mono text-sm">
        <p className="font-bold">Redirecting to Nexus Registration...</p>
      </div>
    </div>
  );
}
