import axios from "axios";
import languagePreferenceService from './services/languagePreferenceService';
import { auth } from './firebase/firebaseConfig';

// frontend/src/api.js
// IMPORTANT: Requires VITE_API_URL env var to be set
// Local: http://localhost:5000
// VM: https://debatesim.us
const API_URL = import.meta.env.VITE_API_URL;
if (!API_URL) {
  throw new Error("VITE_API_URL environment variable is not set");
}
export default API_URL;

// Configure axios with optimized settings
const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 120000, // 2 minutes timeout
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor for optimization
apiClient.interceptors.request.use((config) => {
  // Add timestamp to prevent caching
  config.headers['X-Request-Time'] = Date.now();
  return config;
});

// Add response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.code === 'ECONNABORTED') {
      console.error('Request timeout - AI model may be slow');
    }
    return Promise.reject(error);
  }
);

export const generateAIResponse = async (debater, prompt, model, billDescription = '', fullTranscript = '', roundNum = 1, persona = 'default', debateFormat = 'default', speakingOrder = 'pro-first') => {
  try {
    console.log(`🚀 Generating AI response for ${debater} using ${model} (Round ${roundNum})`);
    console.log(`🔍 DEBUG [frontend]: Full transcript length: ${fullTranscript.length} chars`);
    console.log(`🔍 DEBUG [frontend]: Bill description length: ${billDescription.length} chars`);
    console.log(`🔍 DEBUG [frontend]: Round number: ${roundNum}`);
    console.log(`🔍 DEBUG [frontend]: Prompt: ${prompt}`);
    if (fullTranscript) {
      console.log(`🔍 DEBUG [frontend]: Full transcript preview: ${fullTranscript.substring(0, 300)}...`);
    }
    
    const startTime = Date.now();
    
    const currentLanguage = languagePreferenceService.getCurrentLanguage();
    
    const response = await apiClient.post('/generate-response', {
      debater,
      prompt,
      model, // Pass along the chosen model
      bill_description: billDescription, // Pass bill text for evidence-based arguments
      full_transcript: fullTranscript, // Pass the full debate transcript for context
      round_num: roundNum, // Pass the current round number
      persona: persona, // Pass the persona name for logging
      debate_format: debateFormat, // Pass the debate format
      speaking_order: speakingOrder, // Pass the speaking order for public forum
      language: currentLanguage, // Pass the language preference
    });
    
    const duration = Date.now() - startTime;
    console.log(`✅ AI response generated in ${duration}ms`);
    
    return response.data.response;
  } catch (error) {
    console.error("Error generating AI response:", error);
    throw error;
  }
};

export const getAIJudgeFeedback = async (transcript, model) => {
  try {
    console.log(`🏛️ Generating judge feedback using ${model}`);
    const startTime = Date.now();

    const currentLanguage = languagePreferenceService.getCurrentLanguage();

    const response = await apiClient.post('/judge-feedback', {
      transcript,
      model, // Pass along the chosen judge model
      language: currentLanguage, // Pass the language preference
    });

    const duration = Date.now() - startTime;
    console.log(`✅ Judge feedback generated in ${duration}ms`);

    return response.data.response;
  } catch (error) {
    console.error("Error fetching AI judge feedback:", error);
    throw error;
  }
};

export const saveTranscript = async (transcript, topic, mode, judgeFeedback) => {
  try {
    const response = await apiClient.post('/save-transcript', {
      transcript,
      topic,
      mode,
      judge_feedback: judgeFeedback, // Include judge feedback
    });
    return response.data.message;
  } catch (error) {
    console.error("Error saving transcript:", error);
    throw error;
  }
};

// Dedicated Trainer: Speech Efficiency Analysis (separate chain)
export const analyzeSpeechEfficiency = async (speech, options = {}) => {
  try {
    const currentLanguage = languagePreferenceService.getCurrentLanguage();
    const payload = {
      speech,
      // Allow passing a model or fall back to a safe default
      model: options.model || "openai/gpt-4o-mini",
      // Optional flags to make backend select non-debate pipeline
      mode: "trainer-speech-efficiency",
      persona: "none",
      debate_format: options.debate_format || "none",
      speaking_order: "none",
      round_num: options.round_num || 0,
      speech_type: options.speech_type || "",
      speech_number: options.speech_number || 0,
      language: currentLanguage, // Pass the language preference
    };
    const response = await apiClient.post('/trainer/speech-efficiency', payload);
    if (!response?.data || typeof response.data.response !== 'string') {
      throw new Error('Invalid response from server');
    }
    return response.data.response;
  } catch (error) {
    // Normalize axios error details
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail || error?.message || 'Unknown error';
    console.error("Error analyzing speech efficiency:", status, detail);
    const err = new Error(`Analyze failed${status ? ` (${status})` : ''}: ${detail}`);
    err.status = status;
    err.detail = detail;
    throw err;
  }
};

// --- Lesson Mode: adaptive flashcard review (Leitner boxes) ---
// These are the first backend calls that require an authenticated user:
// the backend verifies a Firebase ID token and derives the caller's uid
// from it, so a fresh token must be attached to every request.
async function getAuthHeaders() {
  const user = auth.currentUser;
  if (!user) {
    throw new Error("You must be signed in to review flashcards.");
  }
  const token = await user.getIdToken();
  return { Authorization: `Bearer ${token}` };
}

// --- Lesson Mode: lesson generation ---
// No auth required -- a generated lesson is reusable content (like a quiz
// question), not per-user state. Generation is idempotent per bill_id +
// bill_text, so calling this again for the same bill reuses the cached
// lesson instead of re-generating.
export const generateLesson = async (billId, billText, options = {}) => {
  const body = {
    bill_id: billId,
    bill_text: billText,
    include_vocabulary: options.includeVocabulary ?? false,
    include_quiz: options.includeQuiz ?? false,
    include_open_response: options.includeOpenResponse ?? false,
  };
  if (options.model) body.model = options.model;
  const response = await apiClient.post('/lesson/generate', body);
  return response.data;
};

// Re-fetch an already-generated lesson by id (e.g. on page refresh/direct
// link), without needing the bill_text again.
export const getLesson = async (lessonId) => {
  const response = await apiClient.get(`/lesson/${lessonId}`);
  return response.data;
};

export const startReviewSession = async (lessonId) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.post(`/lesson/${lessonId}/review/start-session`, {}, { headers });
  return response.data.session;
};

export const getReviewState = async (lessonId) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.get(`/lesson/${lessonId}/review/state`, { headers });
  return response.data;
};

export const submitReviewAnswer = async (lessonId, cardId, correct) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.post(
    `/lesson/${lessonId}/review/answer`,
    { card_id: cardId, correct },
    { headers }
  );
  return response.data;
};

// --- Lesson Mode: multiple-choice quiz ---
export const getQuizQuestions = async (lessonId) => {
  const response = await apiClient.get(`/lesson/${lessonId}/quiz`);
  return response.data;
};

// answers: [{ question_id, selected_index }]
export const submitQuizAnswers = async (lessonId, answers) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.post(
    `/lesson/${lessonId}/quiz/submit`,
    { answers },
    { headers }
  );
  return response.data;
};

// --- Lesson Mode: open-response question ---
export const getOpenResponseQuestion = async (lessonId) => {
  const response = await apiClient.get(`/lesson/${lessonId}/open-response`);
  return response.data;
};

export const submitOpenResponseAnswer = async (lessonId, studentAnswer) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.post(
    `/lesson/${lessonId}/open-response/submit`,
    { student_answer: studentAnswer },
    { headers }
  );
  return response.data;
};

// --- Lesson Mode: student persona builder ---
// The persona is optional and may be fictional. Options are public; reading,
// saving, and deleting a persona are per-user and require an auth token.

export const getPersonaOptions = async () => {
  const response = await apiClient.get('/lesson/persona/options');
  return response.data;
};

export const getPersona = async () => {
  const headers = await getAuthHeaders();
  const response = await apiClient.get('/lesson/persona', { headers });
  return response.data;
};

// persona: { occupation, state, age_range, income_bracket } -- any field may
// be null/omitted (a skipped field).
export const savePersona = async (persona) => {
  const headers = await getAuthHeaders();
  const response = await apiClient.put('/lesson/persona', persona, { headers });
  return response.data;
};

export const deletePersona = async () => {
  const headers = await getAuthHeaders();
  const response = await apiClient.delete('/lesson/persona', { headers });
  return response.data;
};

// --- Lesson Mode: personalized bill-impact narrative ---
// Generates a grounded explanation of how the bill could affect someone
// matching the persona. `persona` (inline, possibly fictional) is optional;
// when omitted the caller's saved persona is used. Requires auth.
export const getPersonalImpact = async (lessonId, { billText, persona, model } = {}) => {
  const headers = await getAuthHeaders();
  const body = { lesson_id: lessonId };
  if (billText) body.bill_text = billText;
  if (persona) body.persona = persona;
  if (model) body.model = model;
  const response = await apiClient.post('/lesson/personal-impact', body, { headers });
  return response.data;
};

// --- Lesson Mode: dynamic opposing debate persona ---
// No auth required -- a generated persona is lesson-scoped, reusable
// content, not per-user state. studentPersona (inline, optional) is the
// same broad occupation/state/age_range/income_bracket shape as the saved
// persona; omitting it is the "persona skipped" path.
export const generateDebatePersona = async (lessonId, { studentPersona, model } = {}) => {
  const body = {};
  if (studentPersona) body.student_persona = studentPersona;
  if (model) body.model = model;
  const response = await apiClient.post(`/lesson/${lessonId}/debate-persona/generate`, body);
  return response.data;
};

export const getSocraticHint = async (lessonId, personaId, fullTranscript = '') => {
  const response = await apiClient.post(`/lesson/${lessonId}/debate-persona/hint`, {
    persona_id: personaId,
    full_transcript: fullTranscript,
  });
  return response.data;
};

// --- Lesson Mode: post-debate reflection (Increment 10) ---
// Auth required -- a reflection is per-user state, read back across every
// lesson debate by getReflectionProgress.
export const submitReflection = async (
  lessonId,
  { transcript, viewChanged, explanation, personaId, model } = {}
) => {
  const headers = await getAuthHeaders();
  const body = { transcript, view_changed: viewChanged };
  if (explanation) body.explanation = explanation;
  if (personaId) body.persona_id = personaId;
  if (model) body.model = model;
  const response = await apiClient.post(`/lesson/${lessonId}/reflection`, body, { headers });
  return response.data;
};

export const getReflectionProgress = async () => {
  const headers = await getAuthHeaders();
  const response = await apiClient.get('/lesson/reflection/progress', { headers });
  return response.data;
};

// --- Lesson Mode: mastery dashboard (Increment 11) ---
// Auth required -- entirely the authenticated user's own progress, read-only.
export const getMasteryDashboard = async () => {
  const headers = await getAuthHeaders();
  const response = await apiClient.get('/lesson/mastery-dashboard', { headers });
  return response.data;
};