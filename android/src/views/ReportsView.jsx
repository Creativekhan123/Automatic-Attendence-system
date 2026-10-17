import React, { useMemo } from 'react';
import { Download, FileText, CheckCircle2, Clock, Calendar, Bus } from 'lucide-react';

export default function ReportsView({ students, buses, attendanceRecords, selectedDate, selectedBus }) {
  // Construct report rows
  const reportData = useMemo(() => {
    const studentMap = new Map();
    students.forEach((s) => studentMap.set(s.student_id, s));

    const rows = [];
    const relevantStudents = selectedBus === 'ALL'
      ? students
      : students.filter((s) => s.bus_id === selectedBus);

    const relevantAttendance = attendanceRecords.filter((r) => {
      const matchesDate = r.attendance_date === selectedDate;
      const matchesBus = selectedBus === 'ALL' || r.bus_id === selectedBus;
      return matchesDate && matchesBus;
    });

    const attendedStudentIds = new Set(relevantAttendance.map((r) => r.student_id));

    // Present records
    relevantAttendance.forEach((att) => {
      const student = studentMap.get(att.student_id) || {
        name: 'Unknown / Deleted',
        class_name: 'N/A',
        bus_id: att.bus_id,
      };
      rows.push({
        student_id: att.student_id,
        name: student.name,
        class_name: student.class_name,
        bus_id: att.bus_id,
        date: att.attendance_date,
        time: att.attendance_time || 'N/A',
        status: att.status || 'Present',
      });
    });

    // Absent/Pending students
    relevantStudents.forEach((student) => {
      if (!attendedStudentIds.has(student.student_id)) {
        rows.push({
          student_id: student.student_id,
          name: student.name,
          class_name: student.class_name,
          bus_id: student.bus_id,
          date: selectedDate,
          time: '--:--',
          status: 'Not Boarded',
        });
      }
    });

    // Sort by ID
    return rows.sort((a, b) => a.student_id.localeCompare(b.student_id));
  }, [students, attendanceRecords, selectedDate, selectedBus]);

  const handleDownloadCsv = () => {
    if (reportData.length === 0) {
      alert('No attendance data available to export.');
      return;
    }

    const headers = ['Student ID', 'Name', 'Class', 'Bus ID', 'Date', 'Status', 'Time'];
    const csvContent = [
      headers.join(','),
      ...reportData.map((row) =>
        [
          `"${row.student_id}"`,
          `"${row.name}"`,
          `"${row.class_name}"`,
          `"${row.bus_id}"`,
          `"${row.date}"`,
          `"${row.status}"`,
          `"${row.time}"`,
        ].join(',')
      ),
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `FleetAttendance_${selectedBus}_${selectedDate}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const presentCount = reportData.filter((r) => r.status === 'Present').length;

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>Official Reports & Export</h2>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          Download certified bus attendance logs for school administration
        </p>
      </div>

      {/* Export Card */}
      <div className="glass-card" style={{ padding: 18, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
              Session Target
            </span>
            <h4 style={{ fontSize: '1rem', fontWeight: 700, color: '#fff' }}>
              {selectedBus === 'ALL' ? 'Complete Fleet' : selectedBus} ({selectedDate})
            </h4>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
              Total Students
            </span>
            <h4 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--accent-emerald)' }}>
              {presentCount} / {reportData.length} Present
            </h4>
          </div>
        </div>

        <button className="btn-primary" onClick={handleDownloadCsv}>
          <Download size={18} />
          <span>Export Official CSV Report</span>
        </button>
      </div>

      {/* Preview Table Header */}
      <div className="section-header">
        <h4>
          <FileText size={16} color="var(--accent-primary)" />
          <span>Report Preview</span>
        </h4>
        <span className="section-counter">{reportData.length} Entries</span>
      </div>

      {/* Preview Rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {reportData.map((row) => {
          const isPresent = row.status === 'Present';
          return (
            <div
              key={row.student_id}
              className="glass-card"
              style={{
                padding: '12px 14px',
                marginBottom: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 700, color: '#fff', fontSize: '0.92rem' }}>
                    {row.name}
                  </span>
                  <span className="badge-tag">ID: {row.student_id}</span>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>
                  Class {row.class_name} • {row.bus_id}
                </div>
              </div>

              <div style={{ textAlign: 'right' }}>
                <div
                  style={{
                    fontSize: '0.74rem',
                    fontWeight: 700,
                    color: isPresent ? 'var(--accent-emerald)' : 'var(--text-muted)',
                  }}
                >
                  {row.status}
                </div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                  {row.time}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
