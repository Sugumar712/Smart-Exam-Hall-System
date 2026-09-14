export type SessionType = 'FN' | 'AN';
export type StudentsPerBenchType = 1 | 2;

export interface DepartmentInput {
  id: string;
  name: string;
  startReg: string;
  endReg: string;
  error?: string;
  count?: number;
}

export interface ExamConfig {
  collegeName: string;
  examTitle: string;
  examPeriod: string;
  session: SessionType;
  examDate: string;
  hallName: string;
  studentsPerHall: number;
  rows: number;
  cols: number;
  studentsPerBench: StudentsPerBenchType;
}

export interface Student {
  department: string;
  registerNumber: string;
  slot: 'A' | 'B';
  seatLabel: string;
}

export interface Bench {
  benchNo: number;
  groupLetter: string;
  row: number;
  col: number;
  student1: Student | null;
  student2: Student | null;
}

export interface BenchGroup {
  groupLetter: string;
  colIndex: number;
  benches: Bench[];
  dept1Header: string;
  dept2Header: string;
}

export interface HallPlan {
  label: string;
  hallIndex: number;
  benches: Bench[];
  groups: BenchGroup[];
  rows: number;
  cols: number;
  totalStudents: number;
  deptSummary: Record<string, number>;
}

export interface SeatingResult {
  halls: HallPlan[];
  config: ExamConfig;
  totalStudents: number;
  totalBenches: number;
  hallCapacity: number;
  overallSummary: Record<string, number>;
}

export interface SearchResult {
  registerNumber: string;
  department: string;
  hallLabel: string;
  groupLetter: string;
  benchNo: number;
  row: number;
  col: number;
  slot: 'A' | 'B';
}
