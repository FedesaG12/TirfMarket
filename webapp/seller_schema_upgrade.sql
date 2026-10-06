-- 1. Add seller_id and status to Deals
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS seller_id UUID REFERENCES public.profiles(id);
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected'));
ALTER TABLE public.deals ADD COLUMN IF NOT EXISTS merchant_name TEXT; -- simpler than managing a separate merchants table for the MVP

-- 2. Update Deals RLS Policies
-- First, drop the old permissive policy
DROP POLICY IF EXISTS "Deals are viewable by everyone" ON public.deals;

-- Everyone can view approved deals
CREATE POLICY "Approved deals are viewable by everyone" ON public.deals FOR SELECT USING (status = 'approved');

-- Sellers can view their own deals
CREATE POLICY "Sellers can view own deals" ON public.deals FOR SELECT USING (seller_id = auth.uid());

-- Sellers can insert their own deals
CREATE POLICY "Sellers can insert own deals" ON public.deals FOR INSERT WITH CHECK (
  seller_id = auth.uid() AND 
  (SELECT account_type FROM public.profiles WHERE id = auth.uid()) = 'seller'
);

-- Admins can view all deals
CREATE POLICY "Admins can view all deals" ON public.deals FOR SELECT USING (public.is_admin());

-- Admins can update all deals (for approval)
CREATE POLICY "Admins can update deals" ON public.deals FOR UPDATE USING (public.is_admin());
