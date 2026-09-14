import React, { useState, useEffect } from 'react';
import {
  ExamConfig,
  DepartmentInput,
  SeatingResult,
  SearchResult,
} from './types';
import { ExamDetailsForm } from './components/ExamDetailsForm';
import { HallBenchConfig } from './components/HallBenchConfig';
import { DepartmentManager } from './components/DepartmentManager';
import { SeatingPreview } from './components/SeatingPreview';
import { StudentSearch } from './components/StudentSearch';
import { PythonExportModal } from './components/PythonExportModal';
import { generateSeatingArrangement } from './utils/seatingAlgorithm';
import {
  Sparkles,
  Layers,
  AlertCircle,
  Users,
  CheckCircle2,
  Building,
  School,
  FileCheck,
} from 'lucide-react';

const INITIAL_CONFIG: ExamConfig = {
  collegeName: 'INDRA GANESAN COLLEGE OF ENGINEERING',
  examTitle: 'Continuous Internal Assessment - I',
  examPeriod: 'EXAMINATIONS - NOV/DEC - 2026',
  session: 'FN',
  examDate: new Date().toISOString().split('T')[0],
  hallName: 'LB-6',
  studentsPerHall: 50,
  rows: 5,
  cols: 5,
  studentsPerBench: 2,
};

const SAMPLE_DEPARTMENTS: DepartmentInput[] = [
  {
    id: 'dept-1',
    name: 'II IT',
    startReg: '811225205045',
    endReg: '811225205069',
    count: 25,
  },
  {
    id: 'dept-2',
    name: 'III BME',
    startReg: '811224121026',
    endReg: '811224121047',
    count: 22,
  },
  {
    id: 'dept-3',
    name: 'II MBA',
    startReg: '811225631022',
    endReg: '811225631024',
    count: 3,
  },
];

export default function App() {
  const [config, setConfig] = useState<ExamConfig>(INITIAL_CONFIG);
  const [departments, setDepartments] = useState<DepartmentInput[]>(SAMPLE_DEPARTMENTS);
  const [seatingResult, setSeatingResult] = useState<SeatingResult | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<SearchResult | null>(null);
  const [isPythonModalOpen, setIsPythonModalOpen] = useState(false);

  const handleConfigChange = (updates: Partial<ExamConfig>) => {
    setConfig((prev) => ({ ...prev, ...updates }));
  };

  const handleLoadTestCase = () => {
    setConfig(INITIAL_CONFIG);
    setDepartments(SAMPLE_DEPARTMENTS);
    const { result, errors: genErrors } = generateSeatingArrangement(INITIAL_CONFIG, SAMPLE_DEPARTMENTS);
    if (result) {
      setSeatingResult(result);
      setErrors([]);
    } else {
      setErrors(genErrors);
    }
  };

  const handleGenerate = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const { result, errors: genErrors } = generateSeatingArrangement(config, departments);
    if (genErrors.length > 0) {
      setErrors(genErrors);
      setSeatingResult(null);
    } else if (result) {
      setErrors([]);
      setSeatingResult(result);
      setSelectedStudent(null);
    }
  };

  // Generate automatically on initial mount
  useEffect(() => {
    const { result, errors: genErrors } = generateSeatingArrangement(config, departments);
    if (result) {
      setSeatingResult(result);
    } else {
      setErrors(genErrors);
    }
  }, []);

  // Quick stats calculation
  const totalBenches = config.rows * config.cols;
  const singleHallCapacity = totalBenches * config.studentsPerBench;
  const currentTotalStudents = departments.reduce((sum, d) => sum + (d.count || 0), 0);
  const remainingSeats = Math.max(0, singleHallCapacity - currentTotalStudents);

  return (
    <div className="min-h-screen bg-slate-100/60 text-slate-900 pb-16 font-sans">
      {/* Header Banner */}
      <header className="bg-slate-900 text-white border-b border-slate-800 shadow-sm print:hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center shadow-xs">
                <School className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                  Smart Exam Hall Seating Arrangement System
                  <span className="text-2xs font-semibold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-400/30">
                    College Edition
                  </span>
                </h1>
                <p className="text-xs text-slate-400">
                  Deterministic bench pairing · 1 or 2 students per bench · Reference-image seating order
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                id="btn-nav-python-export"
                onClick={() => setIsPythonModalOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-200 bg-slate-800 hover:bg-slate-700 hover:text-white border border-slate-700 transition"
              >
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                Python app.py
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 pt-6 space-y-6">
        {/* Dynamic Metric Dashboard */}
        <section aria-label="Seating Metrics" className="grid grid-cols-2 sm:grid-cols-5 gap-3 print:hidden">
          <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs">
            <div className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Total Students
            </div>
            <div className="text-xl font-extrabold text-slate-900 mt-0.5">
              {currentTotalStudents}
            </div>
            <div className="text-2xs text-slate-500 mt-0.5">from register ranges</div>
          </div>

          <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs">
            <div className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Hall Capacity
            </div>
            <div className="text-xl font-extrabold text-blue-600 mt-0.5">
              {singleHallCapacity}
            </div>
            <div className="text-2xs text-slate-500 mt-0.5">
              {totalBenches} benches × {config.studentsPerBench} stud.
            </div>
          </div>

          <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs">
            <div className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Bench Groups
            </div>
            <div className="text-xl font-extrabold text-indigo-600 mt-0.5">
              {config.cols} Groups
            </div>
            <div className="text-2xs text-slate-500 mt-0.5">
              Columns A to {String.fromCharCode(64 + config.cols)}
            </div>
          </div>

          <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs">
            <div className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Mode
            </div>
            <div className="text-sm font-bold text-slate-800 mt-1.5 flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              {config.studentsPerBench === 1 ? '1 Stud. / Bench' : '2 Stud. / Bench'}
            </div>
            <div className="text-2xs text-slate-500 mt-0.5">max per bench</div>
          </div>

          <div className="col-span-2 sm:col-span-1 bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-2xs">
            <div className="text-2xs font-bold uppercase tracking-wider text-slate-500">
              Remaining Seats
            </div>
            <div className={`text-xl font-extrabold mt-0.5 ${remainingSeats > 0 ? 'text-emerald-600' : 'text-slate-600'}`}>
              {remainingSeats}
            </div>
            <div className="text-2xs text-slate-500 mt-0.5">vacant slots</div>
          </div>
        </section>

        {/* Validation Errors Box */}
        {errors.length > 0 && (
          <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-900 animate-fadeIn print:hidden">
            <div className="flex items-start gap-2.5">
              <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-rose-800">
                  Please resolve the following before generating:
                </h4>
                <ul className="mt-1.5 list-disc list-inside text-xs space-y-1">
                  {errors.map((err, idx) => (
                    <li key={idx}>{err}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Configuration Forms */}
        <section aria-label="Exam Configuration" className="space-y-4 print:hidden">
          <ExamDetailsForm config={config} onChange={handleConfigChange} />
          <HallBenchConfig config={config} onChange={handleConfigChange} />
          <DepartmentManager
            departments={departments}
            onChange={setDepartments}
            onLoadTestCase={handleLoadTestCase}
          />

          <div className="flex flex-col sm:flex-row items-center justify-end gap-3 pt-2">
            <button
              type="button"
              id="btn-generate-seating"
              onClick={() => handleGenerate()}
              className="w-full sm:w-auto px-6 py-3 rounded-xl font-bold text-sm text-white bg-blue-600 hover:bg-blue-700 shadow-sm hover:shadow-md transition flex items-center justify-center gap-2"
            >
              <Sparkles className="w-4 h-4 text-blue-200" />
              Generate Seating Order
            </button>
          </div>
        </section>

        {/* Search Bar (Only shown when seating plan exists) */}
        {seatingResult && (
          <section aria-label="Student Register Search" className="print:hidden">
            <StudentSearch
              data={seatingResult}
              selectedStudent={selectedStudent}
              onSelectStudent={setSelectedStudent}
            />
          </section>
        )}

        {/* Live Seating Preview & Exports */}
        {seatingResult && (
          <section aria-label="Live Seating Preview" id="seating-preview-section">
            <SeatingPreview
              data={seatingResult}
              selectedStudent={selectedStudent}
              onOpenPythonModal={() => setIsPythonModalOpen(true)}
            />
          </section>
        )}
      </main>

      {/* Python Export Modal */}
      <PythonExportModal
        isOpen={isPythonModalOpen}
        onClose={() => setIsPythonModalOpen(false)}
      />
    </div>
  );
}
