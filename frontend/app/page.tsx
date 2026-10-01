import Link from "next/link";

const ROADMAP_PHASES = [
  { id: 1, name: "Foundation", done: true },
  { id: 2, name: "Auth & Workspace", done: false },
  { id: 3, name: "File Upload & Storage", done: false },
  { id: 4, name: "Ingestion & Parsing", done: false },
  { id: 5, name: "Chunking & Indexing", done: false },
  { id: 6, name: "Retrieval & RAG", done: false },
  { id: 7, name: "Web Fallback", done: false },
  { id: 8, name: "UI/UX", done: false },
  { id: 9, name: "Production Hardening", done: false },
  { id: 10, name: "Pilot & Scale", done: false },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-medium tracking-widest text-sky-400 uppercase">
        AI Knowledge Assistant
      </p>
      <h1 className="mt-3 text-4xl font-bold tracking-tight text-white sm:text-5xl">
        Jawaban berbasis knowledge base perusahaan,
        <span className="text-sky-400"> lengkap dengan sitasi.</span>
      </h1>
      <p className="mt-6 max-w-2xl text-lg text-slate-300">
        Grounded-first: jawaban hanya dari dokumen internal. Jika bukti tidak
        tersedia, sistem akan menyatakannya secara eksplisit — bukan mengarang.
      </p>

      <div className="mt-8 flex gap-4">
        <Link
          href="/status"
          className="rounded-lg bg-sky-500 px-5 py-2.5 font-medium text-white transition hover:bg-sky-400"
        >
          Lihat Status Sistem
        </Link>
      </div>

      <section className="mt-16">
        <h2 className="text-sm font-semibold tracking-widest text-slate-400 uppercase">
          Fase Eksekusi
        </h2>
        <ol className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {ROADMAP_PHASES.map((phase) => (
            <li
              key={phase.id}
              className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/50 px-4 py-3"
            >
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${
                  phase.done ? "bg-emerald-400" : "bg-slate-600"
                }`}
                aria-hidden
              />
              <span className="text-slate-300">
                Fase {phase.id} — {phase.name}
              </span>
              <span className="ml-auto text-xs text-slate-500">
                {phase.done ? "selesai" : "belum"}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
