-- Add new columns to deals for Groupon-like features
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS location TEXT;
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS fine_print TEXT;
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS highlights TEXT;

-- Create reviews table
CREATE TABLE IF NOT EXISTS public.reviews (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    deal_id UUID REFERENCES public.deals(id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    image_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- RLS for reviews
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;

-- Note: The following policy might already exist or need dropping if it already exists, so we use DO block.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE policyname = 'Reviews are viewable by everyone' AND tablename = 'reviews'
    ) THEN
        CREATE POLICY "Reviews are viewable by everyone" ON public.reviews FOR SELECT USING (true);
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE policyname = 'Users can insert own reviews' AND tablename = 'reviews'
    ) THEN
        CREATE POLICY "Users can insert own reviews" ON public.reviews FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;
END $$;
