import React, { useState, useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { getAuth, onAuthStateChanged, signOut } from "firebase/auth";
import Login from "./components/Login";
import Home from "./components/Home";
import DebateSim from "./components/DebateSim";
import Debate from "./components/Debate";
import Judge from "./components/Judge";
import Legislation from "./components/Legislation";
import PublicTranscriptView from "./components/PublicTranscriptView";
import AboutUs from "./components/AboutUs";
import SpeechTest from "./components/SpeechTest";
import Settings from "./components/Settings";
import History from "./components/History";
import Leaderboard from "./components/Leaderboard";
import Rankings from "./components/Rankings";
import SimulatedDebateHistory from "./components/SimulatedDebateHistory";
import voicePreferenceService from "./services/voicePreferenceService";
import languagePreferenceService from "./services/languagePreferenceService";
import DebateTrainer from "./components/debatetrainer";
import LessonPersona from "./components/LessonPersona";
import LessonHub from "./components/LessonHub";
import LessonOverview from "./components/LessonOverview";
import LessonVocabularyPage from "./components/LessonVocabularyPage";
import LessonQuizPage from "./components/LessonQuizPage";
import LessonOpenResponsePage from "./components/LessonOpenResponsePage";
import LessonPersonalImpactPage from "./components/LessonPersonalImpactPage";
import LessonDebatePersonaPage from "./components/LessonDebatePersonaPage";
import LessonReflectionPage from "./components/LessonReflectionPage";
import LessonReflectionProgress from "./components/LessonReflectionProgress";
import MasteryDashboardPage from "./components/MasteryDashboardPage";

// Component to handle scroll reset on route changes
function ScrollToTop() {
  const location = useLocation();
  
  useEffect(() => {
    // Force scroll to top on route change with multiple methods
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [location.pathname]);
  
  return null;
}

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const auth = getAuth();

  useEffect(() => {
    // Check if a guest user is persisted in localStorage
    const storedUser = localStorage.getItem("user");
    if (storedUser) {
      const user = JSON.parse(storedUser);
      setUser(user);
      setLoading(false);
      // Load voice preference for guest user
      voicePreferenceService.loadVoicePreference(user);
      // Load language preference for guest user
      languagePreferenceService.loadLanguagePreference(user);
    } else {
      // Subscribe to Firebase auth state only if there's no persisted guest user
      const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
        setUser(currentUser);
        setLoading(false);
        // Load voice preference for authenticated user
        if (currentUser) {
          voicePreferenceService.loadVoicePreference(currentUser);
          languagePreferenceService.loadLanguagePreference(currentUser);
        }
      });
      return () => unsubscribe();
    }
  }, [auth]);

  const handleLogout = async () => {
    // Reset scroll position before logout
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    
    try {
      await signOut(auth);
    } catch (error) {
      console.error("Logout error:", error);
    }
    // Remove persisted guest user (if any)
    localStorage.removeItem("user");
    
    // Additional scroll reset after logout process
    setTimeout(() => {
      window.scrollTo(0, 0);
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    }, 0);
    
    setUser(null);
  };

  if (loading) {
    return (
      <div 
        className="main-loading-container"
        style={{
          backgroundColor: '#ededed',
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 9999
        }}
      >
        <div className="main-loading-text">Loading...</div>
      </div>
    );
  }

  return (
    <Router future={{ v7_startTransition: true }}>
      <ScrollToTop />
      <Routes>
        {/* Public routes - accessible without login */}
        <Route path="/shared/:shareId" element={<PublicTranscriptView />} />
        <Route path="/about" element={<AboutUs />} />
        <Route path="/speech-test" element={<SpeechTest />} />
        {/* Public: viewing/filling out a persona needs no auth -- only
            saving/editing/deleting it does (gated inside PersonaBuilder). */}
        <Route path="/lesson/persona" element={<LessonPersona user={user} />} />

        {/* Lesson Mode: generation and viewing need no auth -- only
            per-user actions (review/quiz-submit/open-response-submit/
            personal-impact) do, gated inside each component (shows an
            inline "sign in" message rather than blocking the page). */}
        <Route path="/lesson" element={<LessonHub />} />
        <Route path="/lesson/:lessonId" element={<LessonOverview />} />
        <Route path="/lesson/:lessonId/vocabulary" element={<LessonVocabularyPage />} />
        <Route path="/lesson/:lessonId/quiz" element={<LessonQuizPage />} />
        <Route path="/lesson/:lessonId/open-response" element={<LessonOpenResponsePage />} />
        <Route path="/lesson/:lessonId/personal-impact" element={<LessonPersonalImpactPage />} />
        <Route path="/lesson/:lessonId/debate-persona" element={<LessonDebatePersonaPage />} />
        <Route path="/lesson/:lessonId/reflection" element={<LessonReflectionPage />} />
        <Route path="/lesson/reflection-progress" element={<LessonReflectionProgress />} />
        <Route path="/lesson/mastery-dashboard" element={<MasteryDashboardPage />} />

        {!user ? (
          <Route path="*" element={<Login onLogin={setUser} />} />
        ) : (
          <>
            <Route path="/" element={<Home user={user} onLogout={handleLogout} />} />
            <Route path="/debatesim" element={<DebateSim user={user} />} />
            <Route path="/debate" element={<Debate />} />
            <Route path="/judge" element={<Judge />} />
            <Route path="/legislation" element={<Legislation user={user} />} />
            <Route path="/settings" element={<Settings user={user} onLogout={handleLogout} />} />
            <Route path="/history" element={<History user={user} onLogout={handleLogout} />} />
            <Route path="/simulated-debates" element={<SimulatedDebateHistory user={user} onLogout={handleLogout} />} />
            <Route path="/debatetrainer" element={<DebateTrainer user={user} onLogout={handleLogout} />} />
            <Route path="/leaderboard" element={<Leaderboard user={user} onLogout={handleLogout} />} />
            <Route path="/rankings" element={<Rankings user={user} onLogout={handleLogout} />} />
            <Route path="*" element={<Navigate to="/" />} />
          </>
        )}
      </Routes>
    </Router>
  );
}

export default App;