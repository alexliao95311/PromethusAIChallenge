import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import PersonaBuilder from './PersonaBuilder';
import './LessonPersona.css';

// Lesson Mode: the page that mounts the student persona builder (Increment 7).
// There is no broader Lesson Mode page yet (see docs/LESSON_MODE_ARCHITECTURE.md
// Non-goals), so this route exists purely to host PersonaBuilder for now.
function LessonPersona({ user }) {
  return (
    <div className="lesson-persona-page">
      <Link to="/" className="lesson-persona-back-link">
        <ArrowLeft size={18} />
        <span>Back to Home</span>
      </Link>
      <PersonaBuilder isAuthenticated={!!user} />
    </div>
  );
}

export default LessonPersona;
