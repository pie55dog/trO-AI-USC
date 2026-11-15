/**
 * SAMPLE DATA for the demo page (/demo/notes): what one recorded conversation
 * looks like in your notes. It is shaped exactly like
 * GET /events/{id}/notes/{user_id}, so the demo renders through the same
 * component as real notes. It is labelled "Sample" everywhere it appears and
 * is never shown as a real connection.
 *
 * Jordan Lee and the NVIDIA title are the Figma placeholder person
 * ("Refined / event (connections)"). Every promise's quote is a line of the
 * transcript below, which is what the backend checks before keeping one.
 */

import type { PersonNotes } from "./api";

const line = (speaker: "you" | "them", start: number, text: string) => ({ speaker, start, text });

const TRANSCRIPT = [
  line("you", 0.4, "Hi, I'm Maya. I'm a junior in computer science at Viterbi."),
  line("them", 4.1, "Nice to meet you, Maya. I'm Jordan, I lead a GPU tooling team at NVIDIA."),
  line("you", 9.0, "Oh cool, what does your team actually build?"),
  line("them", 11.6, "Mostly profilers. Tools that show engineers why their code is slow on a GPU."),
  line("you", 17.2, "That's close to my research. I'm making a visualizer for CUDA memory traffic in Professor Lee's lab."),
  line("them", 24.8, "No way. We hire interns on exactly that every summer."),
  line("them", 28.9, "I'll send you the link to our summer internship application tonight."),
  line("you", 33.0, "That would be amazing. I'll email you my project write-up tomorrow."),
  line("them", 37.5, "Please do. And come to the Trojan Network mentoring night next Thursday, I'll be there."),
  line("you", 43.1, "I'll be there. Thanks, Jordan."),
];

export const SAMPLE_NOTES: PersonNotes = {
  person: {
    user_id: 0,
    name: "Jordan Lee",
    position: "Director of Engineering at NVIDIA",
    school: null,
    major: null,
    bio: "Leads a GPU tooling team. Viterbi alum who mentors through the Trojan Network.",
    photo_url: null,
    recorded: true,
    starred: true,
    contact: {},
    tapped_at: "2026-11-14T19:42:00Z",
    notes: { conversation: "ready", voice_notes: 1, follow_ups: 3 },
  },
  conversation_status: "ready",
  conversation: {
    summary:
      "You and Jordan talked about the GPU profiling tools their team builds at NVIDIA, which line up closely with your CUDA memory visualizer in Professor Lee's lab. They said the team hires interns for exactly that kind of work every summer.",
    topics: ["GPU profiling", "CUDA", "Summer internships", "Trojan Network"],
    about_them: [
      "Leads the GPU tooling team at NVIDIA, which builds profilers",
      "Hires interns for that team every summer",
      "Will be at the Trojan Network mentoring night next Thursday",
    ],
    commitments: [
      {
        who: "them",
        what: "send you the link to the summer internship application tonight",
        quote: "I'll send you the link to our summer internship application tonight.",
      },
      {
        who: "you",
        what: "email Jordan your project write-up tomorrow",
        quote: "That would be amazing. I'll email you my project write-up tomorrow.",
      },
      {
        who: "you",
        what: "go to the Trojan Network mentoring night next Thursday",
        quote: "I'll be there. Thanks, Jordan.",
      },
    ],
    follow_ups: [
      "Email Jordan your CUDA visualizer write-up tomorrow",
      "Apply once Jordan sends the internship link",
    ],
    transcript: TRANSCRIPT,
    speaker_method: "two_bracelets",
    updated_at: "2026-11-14T19:47:00Z",
  },
  voice_notes: [
    {
      id: 0,
      category: "person",
      text: "Jordan mentioned their team is hiring for the profiler UI. Ask about it at mentoring night.",
      follow_up: "Ask Jordan about the profiler UI role on Thursday",
      matched_by: "name",
      recorded_at: "2026-11-14T19:49:00Z",
      person_user_id: 0,
      person_name: "Jordan Lee",
    },
  ],
};
