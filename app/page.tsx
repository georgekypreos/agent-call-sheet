import Dashboard from "@/components/Dashboard";

export default function Page() {
  return (
    <main className="max-w-[1040px] mx-auto px-6 pt-6 pb-20">
      <Dashboard topN={10} />
    </main>
  );
}
